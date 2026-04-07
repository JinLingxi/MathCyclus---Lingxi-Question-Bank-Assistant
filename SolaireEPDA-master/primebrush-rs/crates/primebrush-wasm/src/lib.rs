//! 浏览器端 WASM 占位入口；后续接入与 `primebrush-core` 共享的渲染管线。
#![allow(clippy::missing_panics_doc)]

use wasm_bindgen::prelude::*;

#[wasm_bindgen]
pub fn render_primebrush_stub(_payload_json: &str) -> String {
    String::from("<!-- primebrush-wasm: not implemented -->")
}
