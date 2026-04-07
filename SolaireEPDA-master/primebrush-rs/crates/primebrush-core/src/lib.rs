//! PrimeBrush Rust 核心：与 Python `PrimeBrushPlugin` 对齐的迁移骨架。
//!
//! 完整渲染管线尚未接入；后续可将几何/绘图热路径迁入此 crate 并编译为 WASM。

use serde_json::Value;

/// 与 Python 侧 `parse_primebrush` / `render` 契约对齐：可 JSON 序列化的文档载荷。
pub type DiagramPayload = Value;

#[derive(Debug, thiserror::Error)]
pub enum PrimeBrushError {
    #[error("unknown diagram type: {0}")]
    UnknownType(String),
    #[error("serialization: {0}")]
    Serde(#[from] serde_json::Error),
}

/// Rust 侧插件接口（与 `plugin_base.PrimeBrushPlugin` 对应）。
pub trait PrimeBrushPlugin: Send + Sync {
    fn type_names(&self) -> &'static [&'static str];
    fn render_svg(&self, doc: &DiagramPayload, seed: u64) -> Result<String, PrimeBrushError>;
}
