import type { Config } from 'tailwindcss'
import animate from 'tailwindcss-animate'

/**
 * 设计系统映射（docs/03）。
 * 规则：组件层只允许使用这里的 token 别名，禁止写死 hex 色值。
 */
const config: Config = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        background: 'hsl(var(--background))',
        surface: 'hsl(var(--surface))',
        elevated: 'hsl(var(--elevated))',
        hover: 'hsl(var(--hover))',
        border: 'hsl(var(--border))',
        'border-strong': 'hsl(var(--border-strong))',
        foreground: 'hsl(var(--foreground))',
        'foreground-secondary': 'hsl(var(--foreground-secondary))',
        'foreground-muted': 'hsl(var(--foreground-muted))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          soft: 'var(--primary-soft)',
          foreground: 'hsl(0 0% 100%)',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          soft: 'var(--accent-soft)',
          foreground: 'hsl(0 0% 100%)',
        },
        success: {
          DEFAULT: 'hsl(var(--success))',
          soft: 'var(--success-soft)',
          foreground: 'hsl(0 0% 100%)',
        },
        warning: {
          DEFAULT: 'hsl(var(--warning))',
          soft: 'var(--warning-soft)',
          foreground: 'hsl(228 28% 8%)',
        },
        danger: {
          DEFAULT: 'hsl(var(--danger))',
          soft: 'var(--danger-soft)',
          foreground: 'hsl(0 0% 100%)',
        },
        info: {
          DEFAULT: 'hsl(var(--info))',
          soft: 'var(--info-soft)',
          foreground: 'hsl(228 28% 8%)',
        },
        agent: {
          planner: 'hsl(var(--primary))',
          executor: 'hsl(var(--accent))',
          reviewer: 'hsl(var(--warning))',
          replanner: 'hsl(var(--cyan))',
          user: 'hsl(var(--foreground-secondary))',
        },
        chart: {
          violet: '#8b5cf6',
          blue: '#3b82f6',
          cyan: '#06b6d4',
          emerald: '#10b981',
          amber: '#f59e0b',
          rose: '#f43f5e',
          fuchsia: '#d946ef',
          slate: '#64748b',
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      fontFamily: {
        sans: ['Inter', 'PingFang SC', 'Microsoft YaHei', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Consolas', 'monospace'],
      },
      fontSize: {
        // 14px 基准的专业工具密度（docs/03 §3）
        '2xs': ['0.6875rem', { lineHeight: '1rem' }], // 11px Caption
        xs: ['0.75rem', { lineHeight: '1rem' }], // 12px
        sm: ['0.8125rem', { lineHeight: '1.25rem' }], // 13px Secondary
        base: ['0.875rem', { lineHeight: '1.375rem' }], // 14px Body
        lg: ['1rem', { lineHeight: '1.5rem' }], // 16px Title-M
        '2xl': ['1.25rem', { lineHeight: '1.75rem' }], // 20px Title-L
      },
      boxShadow: {
        card: '0 1px 2px rgb(0 0 0 / 40%)',
        pop: '0 8px 24px rgb(0 0 0 / 50%)',
      },
      keyframes: {
        'pulse-soft': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.4' },
        },
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'pulse-soft': 'pulse-soft 2s ease-in-out infinite',
        'fade-in': 'fade-in 0.18s ease-out',
      },
    },
  },
  plugins: [animate],
}

export default config
