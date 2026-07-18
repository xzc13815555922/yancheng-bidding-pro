#!/usr/bin/env python3
"""
generate_dep_graph.py — 生成模块依赖关系图（软件工程 P1-3）
依据 GB/T 8567-2006 + CMMI-DEV v2.0

功能：
  - 用 Python AST 扫描所有 .py 文件的 import 语句
  - 输出 Markdown 依赖图（mermaid 格式）
  - 0 外部依赖（不需 pyreverse / graphviz）

设计原则：
  - 仅生成文档，不改代码
  - 错误处理：单个文件 import 错误不影响整体
"""
import ast
import sys
from pathlib import Path
from datetime import datetime, timezone

PROJ_DIR = Path(__file__).resolve().parents[2]
OUTPUT = PROJ_DIR / "docs" / "module_dependencies.md"


def scan_imports(file_path):
    """扫描单个文件的 import 关系"""
    imports = []
    try:
        with open(file_path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"⚠️ 跳过 {file_path}: {e}")
    return imports


def normalize_module(module_name, project_root):
    """将模块名转为文件相对路径"""
    if module_name.startswith("crawlers.") or module_name.startswith("scripts."):
        parts = module_name.split(".")
        return "/".join(parts) + ".py"
    return module_name


def generate_graph():
    """生成 mermaid 依赖图"""
    py_files = sorted(list(PROJ_DIR.glob("*.py")) +
                      list((PROJ_DIR / "crawlers").glob("*.py")) +
                      list((PROJ_DIR / "scripts" / "utils").glob("*.py")))
    nodes = {}
    edges = []

    # 第一遍：扫描所有模块的 import
    for f in py_files:
        rel = str(f.relative_to(PROJ_DIR))
        imports = scan_imports(f)
        nodes[rel] = imports

    # 第二遍：生成 mermaid 节点
    mermaid_nodes = []
    for module in sorted(nodes.keys()):
        # 简化节点名
        node_id = module.replace("/", "_").replace(".py", "").replace(".", "_")
        mermaid_nodes.append(f"    {node_id}[\"{module}\"]")

    # 第三遍：生成 mermaid 边
    for module, imports in nodes.items():
        node_id = module.replace("/", "_").replace(".py", "").replace(".", "_")
        for imp in imports:
            target = normalize_module(imp, PROJ_DIR)
            target_id = target.replace("/", "_").replace(".py", "")
            if target.startswith("crawlers/") or target.startswith("scripts/") or target in [m.replace("/", "_").replace(".py", "") for m in nodes.keys()]:
                edges.append(f"    {node_id} --> {target_id}")

    # 去重边
    edges = sorted(set(edges))

    md = f"""# ypb 模块依赖关系图

> 生成时间: {datetime.now(timezone.utc).isoformat()}  
> 生成工具: scripts/utils/generate_dep_graph.py (Python AST)  
> 审计批号: 小标-2026-07-18-软件工程 P1-3

## 模块清单（共 {len(nodes)} 个）

"""
    for module in sorted(nodes.keys()):
        md += f"- `{module}`\n"

    md += f"""
## 依赖图（mermaid）

```mermaid
graph TD
{chr(10).join(mermaid_nodes)}
{chr(10).join(edges)}
```

## 模块依赖统计

| 模块 | 导入数 | 主要依赖 |
|------|--------|----------|
"""
    for module in sorted(nodes.keys(), key=lambda m: -len(nodes[m])):
        imports = nodes[module]
        main_deps = [i.split(".")[-1] for i in imports if not i.startswith("_")][:5]
        md += f"| `{module}` | {len(imports)} | {', '.join(main_deps) if main_deps else '-'} |\n"

    md += """
## 变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-07-18 | v1.0 | 初始版本 |
"""
    return md


def main():
    print("🔍 扫描模块依赖...")
    md = generate_graph()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(md, encoding="utf-8")
    print(f"📄 依赖图已生成: {OUTPUT}")
    print(f"   模块数: {md.count('- `')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
