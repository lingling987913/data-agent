import type { Config } from 'tailwindcss'
import tailwindcssAnimate from 'tailwindcss-animate'

const config: Config = {
  darkMode: ['class', '[data-theme="tech-dark"]'],
  content: [
    './src/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        primary: 'rgb(var(--color-primary) / <alpha-value>)',
        primaryAccent: 'rgb(var(--color-primary-accent) / <alpha-value>)',
        brand: 'rgb(var(--color-brand) / <alpha-value>)',
        background: {
          DEFAULT: 'rgb(var(--color-background) / <alpha-value>)',
          secondary: 'rgb(var(--color-background-secondary) / <alpha-value>)',
        },
        surface: 'rgb(var(--color-surface) / <alpha-value>)',
        secondary: 'rgb(var(--color-text-secondary) / <alpha-value>)',
        border: 'rgb(var(--color-border) / 0.15)',
        accent: 'rgb(var(--color-accent) / <alpha-value>)',
        muted: 'rgb(var(--color-muted) / <alpha-value>)',
        destructive: 'rgb(var(--color-destructive) / <alpha-value>)',
        positive: 'rgb(var(--color-positive) / <alpha-value>)',
        warning: 'rgb(var(--color-sa-gold) / <alpha-value>)',
      },
      borderRadius: {
        xl: '10px',
        '2xl': '16px',
        '3xl': '20px',
        '4xl': '24px',
      },
      boxShadow: {
        soft: '0 2px 12px rgba(0,0,0,0.04)',
        medium: '0 4px 24px rgba(0,0,0,0.06)',
        warm: '0 8px 32px rgba(0,0,0,0.08)',
      },
    },
  },
  plugins: [tailwindcssAnimate],
}

export default config
