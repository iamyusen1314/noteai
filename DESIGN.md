# Framer Design System

## 1. Visual Theme & Atmosphere

Framer's design language is built around a dark, immersive canvas that makes UI feel alive. The philosophy is "motion as a first-class citizen" — every element has intention, every interaction has weight. The signature Holo Shader (holographic light-refraction gradient) gives surfaces a premium, almost physical texture. High contrast, generous whitespace, and restrained use of color ensure that when animation fires, it commands full attention. The overall mood is: **bold creative tool meets luxury tech brand**.

---

## 2. Color Palette

| Token | Hex | Usage |
|-------|-----|-------|
| Background | `#0A0A0A` | Page background, deepest layer |
| Surface 1 | `#111111` | Card backgrounds, panels |
| Surface 2 | `#1A1A1A` | Elevated cards, modals |
| Surface 3 | `#242424` | Hover states, input backgrounds |
| Text Primary | `#FFFFFF` | Headlines, primary content |
| Text Secondary | `#999999` | Subtext, labels, captions |
| Text Muted | `#555555` | Disabled, placeholder text |
| Border Default | `rgba(255,255,255,0.08)` | Card borders, dividers |
| Border Hover | `rgba(255,255,255,0.16)` | Interactive border on hover |
| Accent White | `#FFFFFF` | Primary CTA buttons on dark |
| Accent Blue | `#0099FF` | Links, highlights, info states |
| Holo Start | `#FF6FD8` | Holographic gradient start (pink) |
| Holo Mid | `#7B61FF` | Holographic gradient mid (violet) |
| Holo End | `#00D4FF` | Holographic gradient end (cyan) |
| Success | `#22C55E` | Positive states |
| Warning | `#F59E0B` | Caution states |
| Destructive | `#EF4444` | Error, delete states |

### Holo Shader Gradient (signature effect)
```css
background: linear-gradient(135deg, #FF6FD8 0%, #7B61FF 40%, #00D4FF 80%, #22C55E 100%);
```
Use sparingly: hero accents, score indicators, feature highlights. Never as background fill.

---

## 3. Typography

| Role | Font | Weight | Size | Line Height | Letter Spacing |
|------|------|--------|------|-------------|----------------|
| Display | Inter | 800 | 72–96px | 1.05 | -0.04em |
| H1 | Inter | 700 | 48–64px | 1.1 | -0.03em |
| H2 | Inter | 700 | 36–48px | 1.15 | -0.02em |
| H3 | Inter | 600 | 24–32px | 1.2 | -0.01em |
| H4 | Inter | 600 | 20px | 1.3 | 0 |
| Body Large | Inter | 400 | 18px | 1.7 | 0 |
| Body | Inter | 400 | 16px | 1.65 | 0 |
| Small | Inter | 400 | 14px | 1.5 | 0.01em |
| Label | Inter | 500 | 13px | 1.4 | 0.04em |
| Code | JetBrains Mono | 400 | 14px | 1.6 | 0 |

**Font stack:**
```css
font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
```

---

## 4. Component Styling

### Buttons

- **Primary (White on Dark):**
  - Background: `#FFFFFF`
  - Text: `#0A0A0A`
  - Border-radius: `10px`
  - Padding: `10px 20px`
  - Font: 15px / weight 600
  - Hover: `background: #E5E5E5`, `transform: translateY(-1px)`
  - Transition: `all 0.2s ease`

- **Secondary (Ghost):**
  - Background: `transparent`
  - Text: `#FFFFFF`
  - Border: `1px solid rgba(255,255,255,0.15)`
  - Border-radius: `10px`
  - Padding: `10px 20px`
  - Hover: `border-color: rgba(255,255,255,0.35)`, `background: rgba(255,255,255,0.05)`

- **Holo (Gradient Border):**
  - Background: `#111111`
  - Border: 1px gradient border using Holo gradient
  - Text: `#FFFFFF`
  - Implementation: use `background-clip` or pseudo-element wrapper
  - Hover: gradient animates position / glow intensifies

- **Destructive:**
  - Background: `rgba(239,68,68,0.1)`
  - Text: `#EF4444`
  - Border: `1px solid rgba(239,68,68,0.25)`
  - Hover: `background: rgba(239,68,68,0.2)`

### Cards

- Background: `#111111`
- Border: `1px solid rgba(255,255,255,0.08)`
- Border-radius: `16px`
- Shadow: `0 0 0 1px rgba(255,255,255,0.04), 0 24px 48px rgba(0,0,0,0.4)`
- Padding: `24px`
- Hover: border brightens to `rgba(255,255,255,0.16)`, subtle lift `translateY(-2px)`
- Transition: `all 0.25s ease`

**Glass Card variant (for hero/featured):**
```css
background: rgba(255,255,255,0.04);
backdrop-filter: blur(24px);
border: 1px solid rgba(255,255,255,0.1);
```

### Inputs

- Background: `#1A1A1A`
- Border: `1px solid rgba(255,255,255,0.1)`
- Border-radius: `10px`
- Padding: `10px 14px`
- Text: `#FFFFFF`
- Placeholder: `#555555`
- Focus ring: `border-color: rgba(255,255,255,0.4)`, `box-shadow: 0 0 0 3px rgba(123,97,255,0.2)`
- Transition: `border-color 0.2s ease`

### Navigation

- Background: `rgba(10,10,10,0.85)`
- Backdrop-filter: `blur(20px) saturate(180%)`
- Border-bottom: `1px solid rgba(255,255,255,0.06)`
- Height: `60px`
- Item color: `#999999`
- Item hover: `#FFFFFF`
- Active item: `#FFFFFF` with subtle underline or bg pill `rgba(255,255,255,0.08)`
- Logo: white wordmark or monochrome icon

### Badges / Tags

- Background: `rgba(255,255,255,0.06)`
- Border: `1px solid rgba(255,255,255,0.1)`
- Border-radius: `6px`
- Padding: `3px 10px`
- Font: 12px / weight 500
- Text: `#999999`

**Holo badge:**
- Text uses `background: holo-gradient; -webkit-background-clip: text; -webkit-text-fill-color: transparent`

---

## 5. Layout Principles

- **Max content width:** `1200px` (narrow sections: `760px` for text, `960px` for feature grids)
- **Grid:** 12-column, `gap: 24px`
- **Spacing scale (8pt base):** `4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 / 96 / 128px`
- **Section padding:** `96px 0` desktop, `64px 0` mobile
- **Whitespace philosophy:** Breathe first, then add content. Dark background rewards generous spacing — cramped layouts kill the premium feel.
- **Alignment:** Center-aligned for hero sections; left-aligned for content/data sections.

---

## 6. Depth & Elevation

### Shadow system
```css
--shadow-glow-sm: 0 0 16px rgba(123,97,255,0.15);
--shadow-glow-md: 0 0 40px rgba(123,97,255,0.2);
--shadow-glow-lg: 0 0 80px rgba(123,97,255,0.25);
--shadow-dark-sm: 0 4px 16px rgba(0,0,0,0.3);
--shadow-dark-md: 0 8px 32px rgba(0,0,0,0.4);
--shadow-dark-lg: 0 24px 64px rgba(0,0,0,0.5);
```

### Surface hierarchy
1. **Background** `#0A0A0A` — base canvas
2. **Surface 1** `#111111` — default cards, sidebars
3. **Surface 2** `#1A1A1A` — elevated cards, dropdowns
4. **Surface 3** `#242424` — tooltips, top-level modals
5. **Holo highlight** — only for the single most important element on the page

---

## 7. Animation & Motion (Framer's core differentiator)

### Holo Shader Effect
```css
@keyframes holoShift {
  0%   { background-position: 0% 50%; }
  50%  { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}
.holo {
  background: linear-gradient(135deg, #FF6FD8, #7B61FF, #00D4FF, #22C55E, #FF6FD8);
  background-size: 300% 300%;
  animation: holoShift 6s ease infinite;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
```

### Scroll-triggered Fade-in
```css
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(24px); }
  to   { opacity: 1; transform: translateY(0); }
}
.fade-up { animation: fadeUp 0.6s cubic-bezier(0.16,1,0.3,1) forwards; }
```

### Card hover lift
```css
.card {
  transition: transform 0.25s cubic-bezier(0.16,1,0.3,1),
              border-color 0.25s ease,
              box-shadow 0.25s ease;
}
.card:hover {
  transform: translateY(-4px);
  border-color: rgba(255,255,255,0.2);
  box-shadow: 0 24px 48px rgba(0,0,0,0.5), 0 0 32px rgba(123,97,255,0.1);
}
```

### Score / number counter animation
```css
@keyframes countUp {
  from { opacity: 0; transform: scale(0.8); }
  to   { opacity: 1; transform: scale(1); }
}
```
Combine with JS counter (0 → target value over 1.2s with easeOutExpo).

### Pulse glow (for live indicators)
```css
@keyframes pulseGlow {
  0%, 100% { box-shadow: 0 0 6px rgba(123,97,255,0.4); }
  50%       { box-shadow: 0 0 20px rgba(123,97,255,0.8); }
}
```

### Stagger entry (for lists/grids)
Apply `animation-delay: calc(var(--i) * 0.08s)` to each child element.

---

## 8. Do's and Don'ts

**Do:**
- Use dark backgrounds everywhere — `#0A0A0A` as the canvas
- Apply the Holo gradient sparingly (1–2 elements per screen, max)
- Animate on scroll entry — every section should fade/slide in
- Use `cubic-bezier(0.16,1,0.3,1)` (spring-like) for all transforms
- Layer glass-morphism for hero cards and overlays
- Use Inter at 700–800 weight for large headings with tight tracking
- Keep borders extremely subtle (`rgba(255,255,255,0.08)`) — let shadow define depth
- Add micro-interactions to every interactive element (buttons, cards, tabs)

**Don't:**
- Use light/white backgrounds — Framer is a dark-mode-first system
- Overuse the gradient — it must remain special
- Use drop-shadows in lieu of borders — use both intentionally
- Mix warm and cool neutrals — stick to pure grays
- Use animation durations over 0.7s (feels sluggish)
- Use linear easing — always use spring or ease-out curves
- Add decorative elements without motion purpose

---

## 9. Responsive Behavior

- **Breakpoints:** sm `640px`, md `768px`, lg `1024px`, xl `1280px`, 2xl `1536px`
- **Mobile-first:** Yes
- **Touch target minimum:** `44px`
- **Mobile adjustments:**
  - Reduce display font size by ~30% (`clamp()` recommended)
  - Stack grid columns to single column below `md`
  - Increase tap targets on interactive cards
  - Reduce section padding: `96px → 48px`
  - Disable complex hover animations; keep entry animations

---

## 10. Agent Prompt Guide

Quick reference for AI agents building NoteAI Pro with Framer design:

- **Background:** `#0A0A0A`
- **Surface:** `#111111` / `#1A1A1A`
- **Primary font:** Inter (700–800 for headings, 400 for body)
- **Accent gradient:** `linear-gradient(135deg, #FF6FD8, #7B61FF, #00D4FF)`
- **Animation easing:** `cubic-bezier(0.16,1,0.3,1)`
- **Style keywords:** dark canvas, holographic gradients, glass morphism, scroll-triggered animations, spring motion, high contrast, generous whitespace, Inter bold typography

**Example prompt:**
> "Rebuild this dashboard using Framer design system: `#0A0A0A` dark background, `#111111` cards with `rgba(255,255,255,0.08)` borders, Inter 700 headings, holographic gradient (`#FF6FD8 → #7B61FF → #00D4FF`) for score indicators and highlights, glass-morphism nav, scroll-triggered fade-up entry animations with `cubic-bezier(0.16,1,0.3,1)` easing, card hover lift with glow shadow."
