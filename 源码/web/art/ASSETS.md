# 欢迎页插画来源与分层说明

- 文件：`growth-landscape-v1.png`，1536×1024，2,819,681 字节。
- SHA-256：`D008BAB9B415B27FAF6B88F1EBCDA78199D1A322760A07CB1570A135BA5CD540`。
- 生成日期：2026-10-27；使用内置 imagegen 工具，不使用项目模型 SDK/API Key。
- 来源：以用户已认可的 Career-Pilot 欢迎页效果图为编辑参考，保留其手绘山景、书本、指南针外壳和证据纸张。此图为 AI 生成的视觉素材，不是评测数据或功能运行证据。
- 参考图生成文件：`exec-b08bff06-3222-4d82-8ddc-40c452552be2.png`；本资产生成文件：`exec-40ecc6e8-df50-4d4f-8535-a58c536e2ae5.png`。原始生成文件保留，本项目使用已复制的本地素材。
- 主标题、导航、按钮和来源提示由真实 HTML 排版；航线、分数节点、指南针指针由 `src/components/Welcome.tsx` 的 SVG 绘制，不烘焙进图片。
- 背景路径是静态山路，金色动态航线叠在山路中心；CSS 边缘遮罩使纸色与页面融合。1536×1024 是全部动态图形的共同坐标系。
- 减少动态偏好下直接呈现最终路线和状态。55→72→82 来自已有人工整理 Demo Replay，不属于本次模型生成结果。

## 本轮编辑提示词（原文）

```text
Use case: precise-object-edit. Create the production illustration BACKGROUND ASSET for the Career-Pilot webpage from the attached approved mockup.
Keep the original right-side artwork's aesthetic, hand-drawn green ink, muted sage watercolors, warm ivory paper, explorer's compass, open notebook, mountain landscape, winding pale hiking trail, trees, small destination flag, and evidence paper. This must closely resemble the approved reference's actual artwork.
Extract/recompose ONLY that right-side illustrated scene onto one landscape 3:2 canvas. Remove the entire webpage interface, brand, navigation, headline, buttons, footer, and the caption above the illustration. No UI text anywhere. Book's tiny illustrative marks are fine.
Essential layer preparation edits:
1. Remove all three score numbers 55,72,82 AND their circular milestone dots.
2. Remove the thin gold route stroke along the trail. Leave the natural pale hiking trail visible, so an SVG route can later be drawn over its center. The route should wind from the lower middle to the upper right destination flag.
3. Remove the compass's CENTRAL NEEDLE and central compass-rose star completely, leaving a clean light ivory circular face with subtle paper texture. KEEP its beautiful brass/ink outer circular housing, fine tick ring, and N E S W rim labels. The separate needle will be added in code. The compass should be substantially front-facing and circular so an animated needle aligns well.
Composition: big compass in lower left, open notebook behind it in upper left, evidence paper in lower right, tall mountain with small gold flag upper right, winding path between them. Let the illustration fill most of the canvas but remain airy and elegant. Fade all scene edges softly into a uniform warm ivory #F8F7F3 background with no hard rectangular boundary or frame. All drawing contained within the canvas with generous edge safety. No new large objects. No numerals on trail, no route overlay, no compass needle. Preserve the reference's warm sophisticated hand-drawn editorial aesthetic.
```
