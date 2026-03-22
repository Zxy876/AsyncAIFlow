# assembly_worker

处理 `3d_assembly_render` Action：将旧衣基底模型与 DSL 组件模块拼装为最终 GLB。

## 依赖安装

```bash
cd "python-workers/assembly_worker"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 输入 Payload 关键字段

- `taskId`: 任务 ID
- `dsl`: 上游设计 DSL（组件信息）
- `baseModelPath`: 来自 `process_raw_scan` 的清洗后基底模型路径（可选）
- `outputDir`: 导出目录（可选，默认 `/tmp/asyncaiflow-assembly-output`）

## 输出结果

- `modelUrl`: 可给前端展示的模型地址
- `assemblyPath`: 本地导出的 glb 绝对路径
- `meta.stats.moduleCount`: 附加模块数量
