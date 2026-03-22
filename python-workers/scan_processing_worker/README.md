# scan_processing_worker

处理 `process_raw_scan` Action：把手机摄影测量 / LiDAR 生成的粗糙网格（OBJ/PLY 等）清理、减面并输出 Web 友好的 GLB。

## 能力

- 导入原始扫描网格（`.obj` / `.ply` / `.stl` 等）
- 去除孤立碎块（背景噪点）
- 去重顶点，修复常见扫描拓扑问题
- Quadric Decimation 减面（默认目标 <= 20,000 faces）
- 导出 `.glb`

## 依赖安装

```bash
cd "python-workers/scan_processing_worker"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 本地快速测试（不依赖工作流）

```bash
cd "python-workers/scan_processing_worker"
python3 test_local_scan_processing.py /absolute/path/to/raw_scan.obj
```

可选参数：

```bash
python3 test_local_scan_processing.py /absolute/path/to/raw_scan.ply \
  --output /absolute/path/to/cleaned_scan.glb \
  --target-faces 20000 \
  --min-diameter-pct 3.0
```

运行后会打印 JSON 结果，关键字段：

- `modelUrl`: 输出模型地址（默认 `file://...`）
- `glbPath`: 本地输出路径
- `scanStats.inputFaces` / `scanStats.outputFaces`: 减面前后面数

## Action Payload 示例

```json
{
  "scan": {
    "rawModelPath": "/data/raw/coat_scan.obj",
    "outputGlbPath": "/data/processed/coat_scan.web.glb",
    "targetFaces": 20000,
    "isolatedPieceMinDiameterPct": 3.0
  }
}
```
