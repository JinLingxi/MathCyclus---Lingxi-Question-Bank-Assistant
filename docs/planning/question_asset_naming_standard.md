# `questionasset` 图片资源命名规范

## 适用范围

本规范只适用于非 TikZ 图片，例如扫描题图、几何图片、统计图、原始材料截图和 PDF 裁剪图。

题目中已经存在 `tikzpicture` 的图形，继续保留 TikZ 源码，不要把 TikZ 自动生成的辅助 PNG 写成 `questionasset`。

## 引用名格式

```text
^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$
```

要求：

- 只使用小写英文字母、数字和下划线；
- 必须以小写英文字母开头；
- 不使用中文、空格、括号、破折号、路径、扩展名或年份长串；
- 同一道题内按用途和顺序保持唯一。

## 默认命名

| 资源位置 | 默认引用名 |
| --- | --- |
| 题干图片 | `figure_01` |
| 答案图片 | `answer_figure_01` |
| 解析图片 | `solution_figure_01` |
| 原始材料 | `source_01` |
| 缩略图 | `thumbnail_01` |

TeX 示例：

```tex
\questionasset{figure_01}
\questionasset{solution_figure_01}
```

## 显示规则

- `questionasset` 出现在哪里，图片就显示在哪里；
- 图片说明放在数据库的 `caption` 字段，不重复拼接到引用名中；
- TikZ 辅助目录中的 PNG 只作为缓存和导出辅助文件，不参与普通图片引用和未引用图片审计；
- 导出时才把 `questionasset` 解析为实际文件路径。
