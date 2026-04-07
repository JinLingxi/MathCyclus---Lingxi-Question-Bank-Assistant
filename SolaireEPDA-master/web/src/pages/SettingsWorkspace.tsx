import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { FolderInput, Loader2, Save, Trash2 } from "lucide-react";
import {
  apiAgentLlmSettingsGet,
  apiAgentLlmSettingsPut,
  apiAgentSafetyModeGet,
  apiAgentSafetyModePut,
  apiPost,
  type AgentLlmSettingsResponse,
  type AgentSafetyModeOption,
} from "../api/client";
import { useAgentContext } from "../contexts/AgentContext";
import { changeAppLanguage } from "../i18n/changeLanguage";
import type { AppLang } from "../i18n/tauriLocale";

export function SettingsWorkspace({
  onError,
  onSwitchProject,
}: {
  onError: (msg: string | null) => void;
  /** 已打开项目时可选：切换项目并回到欢迎页 */
  onSwitchProject?: () => void | Promise<void>;
}) {
  const { t, i18n } = useTranslation(["settings", "common"]);
  const { setPageContext } = useAgentContext();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [data, setData] = useState<AgentLlmSettingsResponse | null>(null);
  const [mainModel, setMainModel] = useState("");
  const [fastModel, setFastModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [accessSecret, setAccessSecret] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [safetyMode, setSafetyMode] = useState("allegro");
  const [safetyOptions, setSafetyOptions] = useState<AgentSafetyModeOption[]>([]);

  useEffect(() => {
    setPageContext({
      current_page: "settings",
      summary: t("pageSummary"),
    });
    return () => setPageContext(null);
  }, [setPageContext, t]);

  const load = useCallback(async () => {
    setLoading(true);
    setMsg(null);
    onError(null);
    try {
      const [r, safety] = await Promise.all([apiAgentLlmSettingsGet(), apiAgentSafetyModeGet()]);
      setData(r);
      setMainModel(r.main_model);
      setFastModel(r.fast_model);
      setBaseUrl(r.base_url);
      setAccessSecret("");
      setSafetyMode(safety.mode);
      setSafetyOptions(safety.options ?? []);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSave = async () => {
    if (!data?.persist_available) return;
    setSaving(true);
    setMsg(null);
    onError(null);
    try {
      const body: Parameters<typeof apiAgentLlmSettingsPut>[0] = {
        main_model: mainModel,
        fast_model: fastModel,
        base_url: baseUrl,
      };
      if (accessSecret.trim()) {
        body.api_key = accessSecret.trim();
      }
      await apiAgentLlmSettingsPut(body);
      setAccessSecret("");
      setMsg(t("settings:savedProject"));
      await load();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleClearSecret = async () => {
    if (!data?.persist_available) return;
    if (!confirm(t("settings:confirmClearKey"))) return;
    setSaving(true);
    setMsg(null);
    onError(null);
    try {
      await apiAgentLlmSettingsPut({ clear_api_key_override: true });
      setAccessSecret("");
      setMsg(t("settings:clearedKey"));
      await load();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleSwitchProject = async () => {
    if (!onSwitchProject) return;
    setSaving(true);
    setMsg(null);
    onError(null);
    try {
      await apiPost("/api/project/close", {});
      await onSwitchProject();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleSaveSafetyMode = async () => {
    if (!data?.persist_available) return;
    setSaving(true);
    setMsg(null);
    onError(null);
    try {
      await apiAgentSafetyModePut(safetyMode);
      setMsg(t("settings:updatedSafety"));
      await load();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const uiLang: AppLang = i18n.language.startsWith("en") ? "en" : "zh";

  return (
    <div className="h-full overflow-auto p-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">{t("title")}</h1>
          <p className="mt-1 text-sm text-slate-600">{t("intro")}</p>
        </div>
        {onSwitchProject && (
          <button
            type="button"
            disabled={saving}
            onClick={() => void handleSwitchProject()}
            className="inline-flex shrink-0 items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-800 shadow-sm hover:bg-slate-50 disabled:opacity-50"
          >
            <FolderInput className="h-4 w-4" />
            {t("settings:switchProject")}
          </button>
        )}
      </div>

      {loading ? (
        <div className="mt-8 flex items-center gap-2 text-slate-500">
          <Loader2 className="h-5 w-5 animate-spin" />
          {t("settings:loading")}
        </div>
      ) : (
        <div className="mx-auto mt-6 max-w-lg space-y-4">
          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <label className="block text-sm font-medium text-slate-700">{t("settings:uiLanguage")}</label>
            <select
              className="mt-2 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
              value={uiLang}
              onChange={(e) => void changeAppLanguage(e.target.value as AppLang)}
            >
              <option value="zh">{t("settings:langZh")}</option>
              <option value="en">{t("settings:langEn")}</option>
            </select>
          </div>

          {!data?.persist_available && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950">
              {t("settings:needProject")}
            </div>
          )}

          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <label className="block text-sm font-medium text-slate-700">{t("settings:modelBaseUrl")}</label>
            <p className="mt-0.5 text-xs text-slate-500">{t("settings:modelBaseUrlHint")}</p>
            <input
              type="url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              disabled={!data?.persist_available || saving}
              placeholder="https://…"
              className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm disabled:bg-slate-50"
            />
          </div>

          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <label className="block text-sm font-medium text-slate-700">{t("settings:mainModel")}</label>
            <input
              type="text"
              value={mainModel}
              onChange={(e) => setMainModel(e.target.value)}
              disabled={!data?.persist_available || saving}
              className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm disabled:bg-slate-50"
            />
          </div>

          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <label className="block text-sm font-medium text-slate-700">{t("settings:fastModel")}</label>
            <p className="mt-0.5 text-xs text-slate-500">{t("settings:fastModelHint")}</p>
            <input
              type="text"
              value={fastModel}
              onChange={(e) => setFastModel(e.target.value)}
              disabled={!data?.persist_available || saving}
              className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm disabled:bg-slate-50"
            />
          </div>

          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <label className="block text-sm font-medium text-slate-700">{t("settings:accessKey")}</label>
            <p className="mt-0.5 text-xs text-slate-500">
              {t("settings:accessKeyHint", {
                masked: data?.api_key_masked ?? t("settings:notConfigured"),
                override: data?.has_project_api_key_override ? t("settings:overrideSuffix") : "",
              })}
            </p>
            <input
              type="password"
              value={accessSecret}
              onChange={(e) => setAccessSecret(e.target.value)}
              disabled={!data?.persist_available || saving}
              placeholder={data?.persist_available ? t("settings:accessKeyPlaceholder") : ""}
              autoComplete="off"
              className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm disabled:bg-slate-50"
            />
          </div>

          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <label className="block text-sm font-medium text-slate-700">{t("settings:safetyTitle")}</label>
            <p className="mt-0.5 text-xs text-slate-500">{t("settings:safetyHint")}</p>
            <div className="mt-2 space-y-2">
              {safetyOptions.map((op) => (
                <label
                  key={op.id}
                  className={`block cursor-pointer rounded-md border px-3 py-2 text-sm ${
                    safetyMode === op.id ? "border-violet-300 bg-violet-50" : "border-slate-200 bg-white"
                  } ${!data?.persist_available || saving ? "opacity-60" : ""}`}
                >
                  <div className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="agent-safety-mode"
                      value={op.id}
                      checked={safetyMode === op.id}
                      disabled={!data?.persist_available || saving}
                      onChange={(e) => setSafetyMode(e.target.value)}
                    />
                    <span className="font-medium text-slate-800">
                      {t(`safetyOption.${op.id}.label`, { defaultValue: op.label })}
                    </span>
                  </div>
                  <div className="mt-1 pl-6 text-xs text-slate-600">
                    {t(`safetyOption.${op.id}.desc`, { defaultValue: op.description })}
                  </div>
                </label>
              ))}
            </div>
            <div className="mt-3">
              <button
                type="button"
                disabled={!data?.persist_available || saving}
                onClick={() => void handleSaveSafetyMode()}
                className="inline-flex items-center gap-2 rounded-md border border-violet-300 bg-white px-3 py-1.5 text-sm text-violet-700 hover:bg-violet-50 disabled:opacity-50"
              >
                {t("settings:saveSafety")}
              </button>
            </div>
          </div>

          <p className="text-xs text-slate-500">{t("settings:footerNote")}</p>

          {msg && <p className="text-sm text-emerald-700">{msg}</p>}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!data?.persist_available || saving}
              onClick={() => void handleSave()}
              className="inline-flex items-center gap-2 rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {t("settings:saveProject")}
            </button>
            {data?.persist_available && data.has_project_api_key_override && (
              <button
                type="button"
                disabled={saving}
                onClick={() => void handleClearSecret()}
                className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                <Trash2 className="h-4 w-4" />
                {t("settings:clearProjectKey")}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
