import { cva } from 'class-variance-authority'

export const inputVariants = cva(
  `
    w-full px-4 py-2.5 rounded-lg border
    transition-all outline-hidden
    focus:ring-4 text-sm font-medium font-sans
    disabled:opacity-50
  `,
  {
    variants: {
      state: {
        default: `
          bg-[rgb(var(--input-bg))]
          border-[rgb(var(--border))]
          text-[rgb(var(--input-text))]
          placeholder:text-[rgb(var(--input-placeholder))]
          focus:border-[rgb(var(--input-ring))]
          focus:ring-[rgb(var(--input-ring))]/15
        `,
        error: `
          bg-[rgb(var(--input-bg))]
          border-[rgb(var(--danger))]
          text-[rgb(var(--input-text))]
          placeholder:text-[rgb(var(--danger))]/60
          focus:border-[rgb(var(--danger))]
          focus:ring-[rgb(var(--danger))]/15
        `,
      },
    },
    defaultVariants: { state: 'default' },
  }
)

export const selectVariants = cva(
  `
    w-full px-4 py-2.5 rounded-lg border
    transition-all outline-hidden
    focus:ring-4 text-sm font-medium font-sans
    disabled:opacity-50
    cursor-pointer
    bg-[rgb(var(--surface))]
    text-[rgb(var(--foreground))]
  `,
  {
    variants: {
      state: {
        default: `
          border-[rgb(var(--border))]
          focus:border-[rgb(var(--primary))]
          focus:ring-[rgb(var(--primary))]/15
        `,
        error: `
          border-[rgb(var(--danger))]
          focus:border-[rgb(var(--danger))]
          focus:ring-[rgb(var(--danger))]/15
        `,
      },
    },
    defaultVariants: { state: 'default' },
  }
)
