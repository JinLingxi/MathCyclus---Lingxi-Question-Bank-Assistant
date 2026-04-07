// Prevents extra console window on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs;
use std::fs::OpenOptions;
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU16, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

use reqwest::blocking::Client;
use serde_json::json;
use tauri::image::Image;
use tauri::menu::{Menu, MenuItem};
use tauri::path::BaseDirectory;
use tauri::tray::TrayIconBuilder;
use tauri::window::Color;
use tauri::{Emitter, Manager, RunEvent, WindowEvent};
use tauri_plugin_dialog::DialogExt;

// #region agent log
#[allow(unused_variables)]
fn agent_debug_log(hypothesis_id: &str, location: &str, message: &str, data: serde_json::Value) {
    // instrumentation removed
}
// #endregion

struct AppState {
    /// `0` = 尚未就绪（后台线程仍在 `wait_for_health` / 启动嵌入式 Python）。
    backend_port: AtomicU16,
    sidecar: Mutex<Option<Child>>,
    /// 在 `RunEvent::Ready` 时取走并启动后台健康检查；避免在 `setup` 返回前调度 `run_on_main_thread` 失败。
    pending_backend: Mutex<Option<(Option<PathBuf>, String)>>,
}

#[derive(Clone)]
struct AppLocale(Arc<Mutex<String>>);

fn locale_file(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .resolve("app_locale.txt", BaseDirectory::AppConfig)
        .map_err(|e| e.to_string())
}

fn read_locale_file(app: &tauri::AppHandle) -> String {
    if let Ok(p) = locale_file(app) {
        if let Ok(s) = fs::read_to_string(&p) {
            let t = s.trim();
            if t == "en" {
                return "en".into();
            }
        }
    }
    "zh".into()
}

fn write_locale_file(app: &tauri::AppHandle, lang: &str) -> Result<(), String> {
    let p = locale_file(app)?;
    if let Some(parent) = p.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    fs::write(&p, lang).map_err(|e| e.to_string())
}

fn tray_menu_labels(lang: &str) -> (&'static str, &'static str) {
    match lang {
        "en" => ("Show window", "Quit"),
        _ => ("显示窗口", "退出"),
    }
}

fn health_timeout_msg(port: u16, lang: &str) -> String {
    match lang {
        "en" => format!(
            "Local service did not become ready in time: http://127.0.0.1:{}",
            port
        ),
        _ => format!(
            "本地服务未在预期时间内就绪：http://127.0.0.1:{}",
            port
        ),
    }
}

fn spawn_sidecar_err(path: &Path, err: &std::io::Error, lang: &str) -> String {
    match lang {
        "en" => format!(
            "Could not start local service process: {} — {}",
            path.display(),
            err
        ),
        _ => format!(
            "无法启动本地服务进程：{} — {}",
            path.display(),
            err
        ),
    }
}

fn sidecar_dev_hint(lang: &str) -> &'static str {
    match lang {
        "en" => " (no embedded Python; in dev run: python -m uvicorn solaire.web.app:app --host 127.0.0.1 --port 8000)",
        _ => "（未找到嵌入式 Python，请在开发时先启动：python -m uvicorn solaire.web.app:app --host 127.0.0.1 --port 8000）",
    }
}

fn missing_icon_msg(lang: &str) -> &'static str {
    match lang {
        "en" => "Missing application icon",
        _ => "缺少应用图标",
    }
}

#[tauri::command]
fn get_backend_port(state: tauri::State<'_, Arc<AppState>>) -> u16 {
    let start = std::time::Instant::now();
    while start.elapsed() < Duration::from_secs(120) {
        let p = state.backend_port.load(Ordering::SeqCst);
        if p != 0 {
            return p;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    8000
}

#[tauri::command]
fn get_app_locale(state: tauri::State<'_, AppLocale>) -> String {
    state.0.lock().unwrap().clone()
}

#[tauri::command]
fn set_app_locale(app: tauri::AppHandle, lang: String, state: tauri::State<'_, AppLocale>) -> Result<(), String> {
    let normalized = if lang.starts_with("en") { "en" } else { "zh" };
    *state.0.lock().unwrap() = normalized.to_string();
    write_locale_file(&app, normalized)?;
    if let Some(tray) = app.tray_by_id("tray") {
        let (show_t, quit_t) = tray_menu_labels(normalized);
        let show = MenuItem::with_id(&app, "show", show_t, true, None::<&str>).map_err(|e| e.to_string())?;
        let quit = MenuItem::with_id(&app, "quit", quit_t, true, None::<&str>).map_err(|e| e.to_string())?;
        let menu = Menu::with_items(&app, &[&show, &quit]).map_err(|e| e.to_string())?;
        tray.set_menu(Some(menu)).map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Release: 使用 bundle 内嵌入式 Python（`pythonw.exe`）启动 `solaire.desktop_entry`。
/// Debug（`tauri dev`）：默认**不**用嵌入式，改连 `beforeDevCommand` 拉起的 Uvicorn（127.0.0.1:8000），
/// 避免打完包后 `runtime/python` 残留导致开发模式冷启动慢或占满健康检查。
/// 若要在开发里测真实嵌入式：设置环境变量 `SOLAIRE_USE_SIDECAR=1`。
#[cfg(target_os = "windows")]
fn first_existing(paths: impl IntoIterator<Item = PathBuf>) -> Option<PathBuf> {
    for p in paths {
        if p.is_file() {
            return Some(p);
        }
    }
    None
}

/// MSI 安装后资源通常在 `<安装目录>/resources/...`，不是 `<安装目录>/runtime/...`。
/// 依次尝试：resource_dir、Resource resolve、常见回退路径；优先 `python.exe`（配合 CREATE_NO_WINDOW 比 pythonw 更稳）。
#[cfg(target_os = "windows")]
fn resolve_embedded_python(app: &tauri::AppHandle) -> Option<PathBuf> {
    #[cfg(debug_assertions)]
    {
        let _ = app;
        if std::env::var("SOLAIRE_USE_SIDECAR").ok().as_deref() != Some("1") {
            agent_debug_log(
                "H10",
                "main.rs:resolve_embedded_python:debug_none",
                "debug_mode_skip_sidecar",
                json!({ "reason": "SOLAIRE_USE_SIDECAR!=1" }),
            );
            return None;
        }
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let rt = manifest_dir.join("runtime").join("python");
        let found = first_existing([
            rt.join("python.exe"),
            rt.join("pythonw.exe"),
        ]);
        agent_debug_log(
            "H10",
            "main.rs:resolve_embedded_python:debug_found",
            "debug_sidecar_resolution",
            json!({
                "found": found.as_ref().map(|p| p.display().to_string()),
            }),
        );
        found
    }
    #[cfg(not(debug_assertions))]
    {
        let mut c: Vec<PathBuf> = Vec::new();

        if let Ok(rd) = app.path().resource_dir() {
            c.push(rd.join("runtime").join("python").join("python.exe"));
            c.push(rd.join("runtime").join("python").join("pythonw.exe"));
        }

        if let Ok(p) = app.path().resolve("runtime/python/python.exe", BaseDirectory::Resource) {
            c.push(p);
        }
        if let Ok(p) = app.path().resolve("runtime/python/pythonw.exe", BaseDirectory::Resource) {
            c.push(p);
        }

        if let Ok(exe) = std::env::current_exe() {
            if let Some(dir) = exe.parent() {
                c.push(
                    dir.join("resources")
                        .join("runtime")
                        .join("python")
                        .join("python.exe"),
                );
                c.push(
                    dir.join("resources")
                        .join("runtime")
                        .join("python")
                        .join("pythonw.exe"),
                );
                c.push(dir.join("runtime").join("python").join("python.exe"));
                c.push(dir.join("runtime").join("python").join("pythonw.exe"));
            }
        }

        let found = first_existing(c.iter().cloned());
        agent_debug_log(
            "H10",
            "main.rs:resolve_embedded_python:release_result",
            "release_sidecar_resolution",
            json!({
                "found": found.as_ref().map(|p| p.display().to_string()),
                "candidate_count": c.len(),
            }),
        );
        found
    }
}

#[cfg(not(target_os = "windows"))]
fn resolve_embedded_python(_app: &tauri::AppHandle) -> Option<PathBuf> {
    None
}

fn pick_free_port() -> Result<u16, std::io::Error> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let port = listener.local_addr()?.port();
    drop(listener);
    Ok(port)
}

fn wait_for_health(port: u16, lang: &str) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{}/api/health", port);
    // 无超时时 `blocking::get` 在部分环境下可能长时间阻塞，导致整段健康检查卡死、无法写入调试日志。
    let client = Client::builder()
        .timeout(Duration::from_secs(2))
        .connect_timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| e.to_string())?;
    agent_debug_log(
        "H7",
        "main.rs:wait_for_health:start",
        "health_check_loop_started",
        json!({ "port": port, "url": url }),
    );
    let start = std::time::Instant::now();
    let mut first_err: Option<String> = None;
    // 首次冷启动嵌入式 Python + 依赖较多时可能超过 45s
    while start.elapsed() < Duration::from_secs(90) {
        match client.get(&url).send() {
            Ok(resp) => {
                if resp.status().is_success() {
                    agent_debug_log(
                        "H7",
                        "main.rs:wait_for_health:success",
                        "health_check_ok",
                        json!({
                            "elapsed_ms": start.elapsed().as_millis(),
                            "status": resp.status().as_u16()
                        }),
                    );
                    return Ok(());
                }
            }
            Err(e) => {
                if first_err.is_none() {
                    let msg = e.to_string();
                    agent_debug_log(
                        "H7",
                        "main.rs:wait_for_health:first_err",
                        "health_check_first_error",
                        json!({ "err": msg }),
                    );
                    first_err = Some(msg);
                }
            }
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    agent_debug_log(
        "H7",
        "main.rs:wait_for_health:timeout",
        "health_check_timeout",
        json!({
            "elapsed_ms": start.elapsed().as_millis(),
            "first_err": first_err
        }),
    );
    Err(health_timeout_msg(port, lang))
}

fn close_splash(app: &tauri::AppHandle) {
    if let Some(w) = app.get_webview_window("splash") {
        let _ = w.close();
    }
}

fn spawn_python_backend(python_exe: &Path, port: u16, lang: &str) -> Result<Child, String> {
    let work_dir = python_exe
        .parent()
        .ok_or_else(|| "invalid python path".to_string())?;

    let log_path = std::env::temp_dir().join("solaire-desktop-python.log");
    let log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|e| format!("open log {}: {}", log_path.display(), e))?;

    let mut cmd = Command::new(python_exe);
    cmd.current_dir(work_dir)
        .env("PYTHONHOME", work_dir)
        .env("PYTHONUNBUFFERED", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::from(log))
        .args([
            "-m",
            "solaire.desktop_entry",
            "--port",
            &port.to_string(),
        ]);

    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    cmd.spawn()
        .map_err(|e| spawn_sidecar_err(python_exe, &e, lang))
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![get_backend_port, get_app_locale, set_app_locale])
        .setup(|app| {
            agent_debug_log(
                "H1",
                "main.rs:setup:entry",
                "setup_started",
                json!({}),
            );
            let handle = app.handle().clone();
            let lang = read_locale_file(&handle);
            let locale_state = AppLocale(Arc::new(Mutex::new(lang.clone())));
            app.manage(locale_state);

            let embedded = resolve_embedded_python(&handle);
            agent_debug_log(
                "H1",
                "main.rs:setup:embedded",
                "embedded_python_resolved",
                json!({
                    "has_embedded": embedded.is_some(),
                    "pid": std::process::id(),
                    "debug": cfg!(debug_assertions),
                    "exe": std::env::current_exe().ok().map(|p| p.display().to_string()),
                }),
            );

            let state = Arc::new(AppState {
                backend_port: AtomicU16::new(0),
                sidecar: Mutex::new(None),
                pending_backend: Mutex::new(Some((embedded, lang.clone()))),
            });
            app.manage(state.clone());

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::Ready = event {
                let Some(st) = app_handle.try_state::<Arc<AppState>>() else {
                    return;
                };
                let state_arc = (*st).clone();
                let init = state_arc.pending_backend.lock().unwrap().take();
                let Some((embedded, lang_th)) = init else {
                    return;
                };
                let handle_th = app_handle.clone();
                let state_th = state_arc.clone();
                std::thread::spawn(move || {
                agent_debug_log(
                    "H5",
                    "main.rs:thread:backend",
                    "wait_off_main_thread_after_ready",
                    json!({}),
                );

                let backend_result: Result<(u16, Option<Child>), String> = (|| {
                    match embedded {
                        Some(py) => {
                            let port = pick_free_port().map_err(|e| e.to_string())?;
                            let c = spawn_python_backend(&py, port, &lang_th)?;
                            wait_for_health(port, &lang_th).map_err(|e| e.to_string())?;
                            Ok((port, Some(c)))
                        }
                        None => {
                            let port = 8000u16;
                            agent_debug_log(
                                "H5",
                                "main.rs:thread:pre_health",
                                "about_to_wait_health",
                                json!({ "port": port }),
                            );
                            wait_for_health(port, &lang_th).map_err(|e| {
                                format!("{}{}", e, sidecar_dev_hint(&lang_th))
                            })?;
                            Ok((port, None))
                        }
                    }
                })();

                agent_debug_log(
                    "H1",
                    "main.rs:thread:backend_result",
                    "health_wait_finished",
                    json!({ "ok": backend_result.is_ok() }),
                );

                match backend_result {
                    Ok((port, child)) => {
                        let h = handle_th.clone();
                        agent_debug_log(
                            "H11",
                            "main.rs:thread:ui_apply:start",
                            "apply_ui_without_dispatch_start",
                            json!({ "port": port }),
                        );
                        // 先发布端口，避免前端 `get_backend_port` 长时间阻塞导致白屏。
                        state_th.backend_port.store(port, Ordering::SeqCst);
                        *state_th.sidecar.lock().unwrap() = child;

                        agent_debug_log(
                            "H1",
                            "main.rs:setup:backend_ok",
                            "backend_ready",
                            json!({
                                "port": port,
                                "runId": "post-fix"
                            }),
                        );

                        let main_window_exists = h.get_webview_window("main").is_some();
                        agent_debug_log(
                            "H2",
                            "main.rs:setup:main_window",
                            "before_show_main",
                            json!({ "main_window_exists": main_window_exists }),
                        );

                        close_splash(&h);

                        if let Some(window) = h.get_webview_window("main") {
                            let _ = window.set_shadow(false);
                            let _ = window.set_background_color(Some(Color(248, 250, 252, 255)));
                            let _ = window.show();
                            let _ = window.set_focus();
                            let _ = window.emit("backend-ready", port);
                        }

                        agent_debug_log(
                            "H3",
                            "main.rs:setup:tray_icon",
                            "loading_tray_icon",
                            json!({}),
                        );
                        let tray_icon = match Image::from_bytes(include_bytes!(
                            "../icons/tray-icon.png"
                        )) {
                            Ok(i) => i,
                            Err(e) => {
                                agent_debug_log(
                                    "H3",
                                    "main.rs:setup:tray_icon_err",
                                    "tray_icon_decode_failed",
                                    json!({
                                        "err": format!("{}: {}", missing_icon_msg(&lang_th), e),
                                    }),
                                );
                                return;
                            }
                        };

                        let (show_t, quit_t) = tray_menu_labels(&lang_th);
                        let show = match MenuItem::with_id(
                            &h,
                            "show",
                            show_t,
                            true,
                            None::<&str>,
                        ) {
                            Ok(m) => m,
                            Err(e) => {
                                agent_debug_log(
                                    "H4",
                                    "main.rs:setup:tray_menu",
                                    "menu_item_failed",
                                    json!({ "err": e.to_string() }),
                                );
                                return;
                            }
                        };
                        let quit = match MenuItem::with_id(
                            &h,
                            "quit",
                            quit_t,
                            true,
                            None::<&str>,
                        ) {
                            Ok(m) => m,
                            Err(e) => {
                                agent_debug_log(
                                    "H4",
                                    "main.rs:setup:tray_menu",
                                    "menu_quit_failed",
                                    json!({ "err": e.to_string() }),
                                );
                                return;
                            }
                        };
                        let menu = match Menu::with_items(&h, &[&show, &quit]) {
                            Ok(m) => m,
                            Err(e) => {
                                agent_debug_log(
                                    "H4",
                                    "main.rs:setup:tray_menu",
                                    "menu_build_failed",
                                    json!({ "err": e.to_string() }),
                                );
                                return;
                            }
                        };

                        let app_handle = h.clone();
                        if let Err(e) = TrayIconBuilder::with_id("tray")
                            .icon(tray_icon)
                            .menu(&menu)
                            .tooltip("SolEdu")
                            .on_menu_event(move |app, event| match event.id.as_ref() {
                                "quit" => {
                                    if let Ok(mut guard) =
                                        app.state::<Arc<AppState>>().sidecar.lock()
                                    {
                                        if let Some(mut c) = guard.take() {
                                            let _ = c.kill();
                                        }
                                    }
                                    app.exit(0);
                                }
                                "show" => {
                                    if let Some(w) = app.get_webview_window("main") {
                                        let _ = w.show();
                                        let _ = w.set_focus();
                                    }
                                }
                                _ => {}
                            })
                            .on_tray_icon_event(move |tray, event| {
                                if let tauri::tray::TrayIconEvent::Click {
                                    button: tauri::tray::MouseButton::Left,
                                    button_state: tauri::tray::MouseButtonState::Up,
                                    ..
                                } = event
                                {
                                    let app = tray.app_handle();
                                    if let Some(w) = app.get_webview_window("main") {
                                        let _ = w.show();
                                        let _ = w.set_focus();
                                    }
                                }
                            })
                            .build(&h)
                        {
                            agent_debug_log(
                                "H4",
                                "main.rs:setup:tray_build",
                                "tray_build_failed",
                                json!({ "err": e.to_string() }),
                            );
                            return;
                        }

                        agent_debug_log(
                            "H4",
                            "main.rs:setup:tray_built",
                            "tray_ok_before_main_close_handler",
                            json!({
                                "main_exists": app_handle.get_webview_window("main").is_some()
                            }),
                        );

                        if let Some(win) = app_handle.get_webview_window("main") {
                            let win_clone = win.clone();
                            win.on_window_event(move |ev| {
                                if let WindowEvent::CloseRequested { api, .. } = ev {
                                    api.prevent_close();
                                    let _ = win_clone.hide();
                                }
                            });
                        } else {
                            agent_debug_log(
                                "H2",
                                "main.rs:setup:main_missing",
                                "main_window_none_after_tray",
                                json!({}),
                            );
                        }
                        agent_debug_log(
                            "H11",
                            "main.rs:thread:ui_apply:done",
                            "apply_ui_without_dispatch_done",
                            json!({ "port": port }),
                        );
                    }
                    Err(e) => {
                        agent_debug_log(
                            "H1",
                            "main.rs:thread:backend_err",
                            "backend_health_failed",
                            json!({ "err": e }),
                        );
                        let h_close = handle_th.clone();
                        let r_close = handle_th.run_on_main_thread(move || {
                            close_splash(&h_close);
                        });
                        agent_debug_log(
                            "H6",
                            "main.rs:thread:main_dispatch_err",
                            "close_splash_dispatch",
                            json!({
                                "ok": r_close.is_ok(),
                                "err": r_close.as_ref().err().map(|e| e.to_string()),
                            }),
                        );
                        let h_dialog = handle_th.clone();
                        let msg = e;
                        std::thread::spawn(move || {
                            let _ = h_dialog.dialog().message(msg).blocking_show();
                            h_dialog.exit(1);
                        });
                    }
                }
                });
            }
            if let RunEvent::Exit = event {
                // Child is killed on explicit quit from tray; best-effort on other exits.
            }
        });
}
