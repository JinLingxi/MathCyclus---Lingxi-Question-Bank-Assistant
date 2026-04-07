# PrimeBrush（Rust）

Python 包 `solaire.primebrush` 的长期迁移目标：几何与绘图热路径在此实现，经 **PyO3** 供后端调用，经 **wasm-bindgen** 供浏览器调用。

## 构建

```bash
cargo check   # 工作区检查
```

### PyO3 扩展（可选）

使用 [maturin](https://www.maturin.rs/) 在 `crates/primebrush-pyo3` 目录构建，产出 Python 模块 `primebrush_rs`。未安装时，Python 自动使用纯 Python 插件实现。

### WASM（可选）

```bash
cd crates/primebrush-wasm
wasm-pack build --target web
```

当前 API 为占位，待与 `primebrush-core` 对接。

## 目录

| Crate | 说明 |
|-------|------|
| `primebrush-core` | 公共类型与插件 trait 骨架 |
| `primebrush-pyo3` | `primebrush_rs` Python 模块 |
| `primebrush-wasm` | 浏览器 WASM 占位 |
