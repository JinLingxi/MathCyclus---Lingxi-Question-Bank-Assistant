//! Python 模块 `primebrush_rs`：由 maturin 构建后可供 `solaire.primebrush.api.render` 优先调用。
//! 当前占位：导入失败时 Python 使用纯 Python 插件渲染。

use pyo3::prelude::*;
use pyo3::types::PyDict;

#[pyfunction]
#[pyo3(signature = (doc, seed=None))]
fn render(doc: Bound<'_, PyDict>, seed: Option<u64>) -> PyResult<String> {
    let _ = (doc, seed);
    Err(PyErr::new::<pyo3::exceptions::PyNotImplementedError, _>(
        "primebrush_rs: Rust renderer not wired yet; use Python implementation",
    ))
}

#[pymodule]
fn primebrush_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(render, m)?)?;
    Ok(())
}
