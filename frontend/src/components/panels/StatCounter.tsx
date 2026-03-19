interface StatCounterProps {
  value: number
  label: string
  color: string
}

export function StatCounter({ value, label, color }: StatCounterProps) {
  const valueColorClass = color === '#44ff66'
    ? 'text-[#44ff66]'
    : color === '#7a8a9a'
      ? 'text-[#7a8a9a]'
      : color === '#ff4444'
        ? 'text-[#ff4444]'
        : color === '#44ccff'
          ? 'text-[#44ccff]'
          : 'text-[#8899aa]'
  const labelColorClass = color === '#7a8a9a'
    ? 'text-[#6a7a8a]'
    : valueColorClass

  return (
    <div className="flex-1 text-center">
      <div className={`text-2xl font-bold leading-[1.2] ${valueColorClass}`}>{value}</div>
      <div className={`text-[11px] tracking-[0.5px] opacity-70 ${labelColorClass}`}>{label}</div>
    </div>
  )
}