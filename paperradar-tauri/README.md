# PaperRadar Tauri Frontend

这是 PaperRadar 的新桌面端前端骨架，目标是替换 PySide6 界面层，同时保留旧 PySide6 版本作为回退。

## 技术栈

- Tauri v2
- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui 风格组件
- lucide-react
- Python sidecar / 本地 FastAPI 后端

## 启动

安装依赖：

```powershell
cd D:\PaperRadar\paperradar-tauri
npm install
```

启动 Python 后端，读取现有 PaperRadar 本地缓存和 Profile：

```powershell
cd D:\PaperRadar\paperradar-tauri
npm run backend:dev
```

另开一个终端启动前端开发预览：

```powershell
cd D:\PaperRadar\paperradar-tauri
npm run dev
```

然后打开：

```text
http://127.0.0.1:1420
```

如果后端没有启动，前端会自动回退到 mock 数据，方便继续做 UI 开发。

Tauri 开发模式：

```powershell
cd D:\PaperRadar\paperradar-tauri
npm run tauri:dev
```

注意：Tauri 需要 Rust/Cargo 工具链。本机当前没有 `cargo`，因此 React 前端可以构建和预览，但桌面壳暂时不能编译。

## 当前完成范围

当前版本交付可运行的现代化 UI 骨架，并已完成第一批真实后端读取：

- 左侧现代导航；
- 今日发现页面；
- 历史调研页面；
- 研究方向页面；
- 统一 Button / Card / Badge / Select / Switch / EmptyState；
- 今日发现和历史调研共用 `PaperTable`；
- 右侧论文详情 Sheet；
- TypeScript 数据结构；
- mock 数据兜底；
- FastAPI 后端可读取现有 SQLite 文献缓存；
- FastAPI 后端可读取现有 Profile；
- 前端 API 层优先请求 `http://127.0.0.1:8765`，失败自动回退 mock。

## 已接入 API

- `GET /api/status`
- `GET /api/papers/today`
- `GET /api/papers/history`
- `GET /api/profiles`
- `POST /api/profiles`
- `PUT /api/profiles/{profile_id}`
- `DELETE /api/profiles/{profile_id}`

## 预留 API

以下接口已保留入口，但还未接入真实异步任务：

- `POST /api/papers/check`
- `POST /api/papers/stop`
- `POST /api/history/start`
- `POST /api/history/stop`
- `POST /api/reports/today`
- `POST /api/reports/history`
- `GET /api/logs/recent`

## 下一阶段迁移计划

1. 将 `DailySearchService` 接入 `/api/papers/check`，改成异步任务并提供进度。
2. 将 `HistoricalSurveyService` 接入 `/api/history/start`，保留缓存复用逻辑。
3. 接入报告生成和打开报告文件夹。
4. 接入日志和用户友好的错误详情。
5. 安装 Rust/Cargo 后编译 Tauri 桌面壳。
6. 将 Python 后端作为 Tauri sidecar 打包。
7. 生成 Windows 安装包。
