import * as React from 'react'

interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  value?: number
  indicatorClassName?: string
}

/**
 * Shadcn-style progress primitive used for compact battery indicators.
 *
 * @param value Numeric progress value in percentage.
 * @param className Optional class names for the root element.
 * @param props Remaining native div props.
 * @returns A styled progress bar with an inner indicator.
 */
const Progress = React.forwardRef<HTMLDivElement, ProgressProps>(
  ({ className = '', value = 0, indicatorClassName = '', ...props }, ref) => {
    const safeValue = Math.max(0, Math.min(100, value))
    return (
      <div
        ref={ref}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={safeValue}
        className={`relative h-2.5 w-full overflow-hidden rounded-full bg-[rgba(148,163,184,0.2)] ${className}`}
        {...props}
      >
        <div
          className={`h-full w-full flex-1 transition-transform ${indicatorClassName}`}
          style={{ transform: `translateX(-${100 - safeValue}%)` }}
        />
      </div>
    )
  },
)

Progress.displayName = 'Progress'

export { Progress }