import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-lg font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        /** 主操作：品牌紫实底 */
        default: 'bg-primary text-primary-foreground hover:bg-primary/90 shadow-card',
        /** soft-*：12% 透明底 + 同色文字（docs/03 §5.1） */
        soft: 'bg-primary-soft text-primary hover:bg-primary/20',
        ghost: 'text-foreground-secondary hover:bg-hover hover:text-foreground',
        outline: 'border border-border-strong bg-transparent text-foreground-secondary hover:bg-hover',
        secondary: 'bg-elevated text-foreground hover:bg-hover',
        danger: 'bg-danger-soft text-danger hover:bg-danger/20',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-8 px-3.5 text-sm',
        sm: 'h-6 px-2.5 text-xs',
        lg: 'h-9 px-5 text-base',
        icon: 'h-8 w-8',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button'
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
  },
)
Button.displayName = 'Button'

export { buttonVariants }
