import { cva } from 'class-variance-authority'

export const buttonVariants = cva(
  // Focus ring uses clinical teal; Inter-based font, tight tracking.
  'inline-flex items-center justify-center rounded-md text-sm font-semibold transition-all focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-teal-500/50 disabled:pointer-events-none disabled:opacity-40 active:scale-[0.98] font-sans tracking-tight',
  {
    variants: {
      variant: {
        // Clinical teal: trusted and professional.
        primary:
          'bg-teal-600 text-white hover:bg-teal-700 shadow-sm border border-teal-700/10',
        // Soft slate: non-threatening secondary action.
        secondary:
          'bg-slate-100 text-slate-900 hover:bg-slate-200 border border-slate-200 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700 dark:border-slate-700',
        // Outline: low-priority navigation.
        outline:
          'border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:hover:bg-slate-800 dark:text-slate-200',
        // Ghost: subtle dashboard interactions.
        ghost:
          'bg-transparent hover:bg-teal-50 text-teal-700 dark:hover:bg-slate-800 dark:text-teal-300',
        // Rose-based danger: clear but not "bloody" bright red.
        danger: 'bg-rose-600 text-white hover:bg-rose-700 shadow-sm',
      },
      size: {
        // Slightly larger hit targets than default for touch use.
        sm: 'h-8 px-3 text-xs gap-1.5',
        md: 'h-11 px-5 py-2.5 gap-2',
        lg: 'h-13 px-8 text-base gap-3',
      },
      fullWidth: {
        true: 'w-full',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'md',
      fullWidth: false,
    },
  }
)
