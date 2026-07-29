# 技术栈、CMS与数据

## 目录

- 技术选择
- CMS规则
- 数据分层
- 内容接口
- 成本表

## 技术选择

只推荐一个最终方案：

| 方案 | 适用条件 | 不适用条件 |
|---|---|---|
| 原生HTML/CSS/JS | 极小单页、几乎不更新、无复杂状态 | 多页面内容、组件复用、登录数据库 |
| Astro | 内容型、多页面、SEO、静态生成、少量交互岛 | 以客户端状态为核心的应用 |
| Vite + React + TypeScript | 高交互前端、无需SSR、React生态 | 大量需要服务端SEO的动态页面 |
| Vite + Vue | 现有Vue项目或用户明确指定 | 仅因“也很主流”而新增 |
| Next.js | React全栈、登录、数据库、服务端逻辑、动态SEO | 简单内容站或纯静态展示 |

React默认使用TypeScript。先用CSS完成普通过渡；只有复杂时间线或滚动编排才使用GSAP。

个人非商业项目默认Vercel。商业项目默认比较Cloudflare Pages；若SSR、区域、数据库或团队流程不兼容，说明原因、成本后选择例外。

## CMS规则

1. 每月更新少于2次、1人维护且接受Codex/Git：Markdown或MDX。
2. 每月更新至少2次，或必须浏览器编辑：优先Decap CMS。
3. 出现多语言、角色权限、审批流，或至少3名编辑者：比较Sanity与Storyblok，只选一个。

CMS只管理内容、图片、链接、SEO和发布状态。布局、字体、颜色、间距和动效留在代码中。

后台允许新增、排序和归档。默认不永久删除。内容必须能导出为Markdown/JSON、原始图片和资源清单，并保留稳定ID。

发布流程固定为：

```text
编辑 → 预览构建 → 自动检查 → 用户确认 → 正式发布
```

## 数据分层

- 短结构化内容：JSON、YAML或TypeScript数据。
- 长文章：Markdown/MDX。
- 图片：独立原文件和元数据。
- Web App演示数据：JSON。
- 真实用户和业务数据：Postgres/Supabase等数据库。
- 视觉变量：代码中的设计系统，不放CMS。

不要默认用Python批量生成HTML页面。让Astro、Next.js或选定框架根据内容生成路由。Python用于导入、迁移、整理和审计。

## 内容接口

```ts
type PublishStatus = "draft" | "review" | "published" | "archived";

interface ImageAsset {
  src: string;
  width: number;
  height: number;
  ratio: string;
  alt: string;
  source: string;
}

interface SeoFields {
  title: string;
  description: string;
  canonical?: string;
  noindex: boolean;
}

interface ContentItem {
  id: string;
  status: PublishStatus;
  archived: boolean;
  demo: boolean;
  title: string;
  slug: string;
  images: ImageAsset[];
  seo: SeoFields;
}
```

Web App还必须定义用户、角色、所有权、数据库约束、RLS策略和失败状态。

## 成本表

在 `技术确认` 前填写：

- 依赖与许可证
- 域名
- 托管
- 数据库/Auth免费额度
- 图片和文件存储
- 邮件、表单、地图和第三方API
- 超额价格
- 意外收费风险
- 免费替代
- 首年最低预计

任何可能收费的服务必须先获得用户确认。
