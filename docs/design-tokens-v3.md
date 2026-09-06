# 微信小程序 UI 视觉规范 v3.0

## 配色方案

### 背景渐变
- 主背景：linear-gradient(180deg, #0A0E2A 0%, #1A1F4D 60%, #24243E 100%)
- 替代背景（注册页）：linear-gradient(135deg, #0F0C29 0%, #302B63 50%, #24243E 100%)

### 主色调（莫比乌斯环 / 强调色）
- 紫粉渐变：linear-gradient(135deg, #9D5CFF 0%, #FF6BCB 100%)
- 紫色：#9D5CFF / #6B3FA0
- 粉色：#FF6BCB / #FF9DE2
- 中心球体：radial-gradient(circle at 30% 30%, rgba(199,125,255,0.9) 0%, rgba(255,157,226,0.7) 100%)

### 荧光/发光色
- 荧光紫：#B388FF / #C77DFF
- 青荧光：#00E5FF / #00CED1
- 高光白：#FFFFFF / #F0F0FF

### 文字颜色
- 主标题：#FFFFFF
- 副标题/辅助：rgba(255,255,255,0.7) ~ rgba(255,255,255,0.9)
- 正文：#E8E8F0
- 辅助文字：rgba(255,255,255,0.5)

### 输入框/卡片背景
- 毛玻璃卡片：rgba(20, 15, 40, 0.75) + backdrop-filter: blur(20rpx)
- 输入框：rgba(255,255,255,0.06)
- 输入框边框：rgba(179, 136, 255, 0.3)
- 输入框聚焦：rgba(179, 136, 255, 0.6)

## 字体层级
- 主标题（导航栏）：32rpx / font-weight: 700
- 大标题（页面标题）：28rpx / font-weight: 700
- 中标题（section标题）：24rpx / font-weight: 600
- 正文：22rpx / font-weight: 400
- 辅助文字：18rpx / color: rgba(255,255,255,0.6)
- 按钮文字：24rpx / font-weight: 700

## 圆角/间距
- 卡片圆角：24rpx
- 输入框圆角：16rpx
- 按钮圆角：40rpx（胶囊形）
- 小元素圆角：12rpx
- 基础间距：16rpx / 24rpx / 32rpx / 40rpx

## 阴影与发光
- 卡片阴影：0 12rpx 40rpx rgba(0,0,0,0.4)
- 输入框聚焦发光：0 0 20rpx rgba(179,136,255,0.3)
- 按钮发光：0 8rpx 24rpx rgba(157,92,255,0.5)
- 莫比乌斯环外发光：0 0 60rpx rgba(179,136,255,0.4)

## 动效时间
- 环体旋转：12s linear infinite
- 光点闪烁：2s ease-in-out infinite
- 呼吸灯：4s ease-in-out infinite
- 入场动画：0.5s cubic-bezier(0.23, 1, 0.32, 1)
