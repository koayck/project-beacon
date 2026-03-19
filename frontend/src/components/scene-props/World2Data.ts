export const W2_C_ROAD = '#2c2c32'
export const W2_C_LINE = '#D7CDA5'
export const W2_C_PARK = '#286C34'
export const W2_C_TRUNK = '#5F4126'
export const W2_C_LEAF = '#267632'
export const W2_C_CANAL = '#1a4a7a'
export const W2_C_SLAB = '#94A2AF'

export type World2RoadStrip = readonly [number, number, number, number]
export type World2ShophouseSpec = readonly [number, number, number, number, number, string, string]
export type World2MidRiseSpec = readonly [number, number, number, number, number, string, string]
export type World2TreePos = readonly [number, number]
export type World2ParkRect = readonly [number, number, number, number]

export const W2_SHOPHOUSES: readonly World2ShophouseSpec[] = [
  [34, 38, 4, 12, 9, '#F5E6C8', '#E8D5B0'],
  [38, 38, 4, 12, 12, '#B5D4E8', '#A0C4D8'],
  [-42, 38, 4, 12, 12, '#F0E0A8', '#F5E8A0'],
  [-46, 38, 4, 12, 9, '#E8B5B0', '#D4A09A'],
  [-50, 38, 4, 12, 12, '#B0D8C0', '#A0C8B0'],
  [-6, -42, 4, 12, 12, '#C2DDE8', '#B5D4E8'],
  [-10, -42, 4, 12, 9, '#F5E6C8', '#E8D5B0'],
  [-14, -42, 4, 12, 12, '#E8B5B0', '#D4A09A'],
  [-18, -42, 4, 12, 9, '#F5E8A0', '#E8DC90'],
  [-22, -42, 4, 12, 12, '#B0D8C0', '#A0C8B0'],
  [6, -42, 4, 12, 9, '#E8E4E0', '#D8D4D0'],
  [10, -42, 4, 12, 12, '#C89478', '#B88468'],
  [14, -42, 4, 12, 9, '#F0C4BE', '#E8B5B0'],
  [18, -42, 4, 12, 12, '#D4A09A', '#C89488'],
  [42, -12, 12, 4, 9, '#F5E6C8', '#E8D5B0'],
  [42, -8, 12, 4, 12, '#B5D4E8', '#A0C4D8'],
  [42, -4, 12, 4, 9, '#F5E8A0', '#E8DC90'],
  [42, 0, 12, 4, 12, '#E8B5B0', '#D4A09A'],
  [42, 4, 12, 4, 9, '#B0D8C0', '#A0C8B0'],
  [42, 8, 12, 4, 12, '#E8E4E0', '#D8D4D0'],
  [42, 12, 12, 4, 9, '#C89478', '#B88468'],
  [-50, -12, 12, 4, 12, '#C2DDE8', '#B5D4E8'],
  [-50, -8, 12, 4, 9, '#F0C4BE', '#E8B5B0'],
  [-50, -4, 12, 4, 12, '#F0E0A8', '#F5E8A0'],
  [-50, 0, 12, 4, 9, '#D4A09A', '#C89488'],
  [-50, 4, 12, 4, 12, '#C0E0D0', '#B0D8C0'],
  [-50, 8, 12, 4, 9, '#F0ECE8', '#E8E4E0'],
  [6, 52, 4, 12, 9, '#F5E6C8', '#E8D5B0'],
  [10, 52, 4, 12, 12, '#B5D4E8', '#A0C4D8'],
  [14, 52, 4, 12, 9, '#E8B5B0', '#D4A09A'],
  [18, 52, 4, 12, 12, '#F5E8A0', '#E8DC90'],
  [22, 52, 4, 12, 9, '#B0D8C0', '#A0C8B0'],
  [-6, 52, 4, 12, 12, '#E8E4E0', '#D8D4D0'],
  [-10, 52, 4, 12, 9, '#F0C4BE', '#E8B5B0'],
  [-14, 52, 4, 12, 12, '#C2DDE8', '#B5D4E8'],
  [-6, -52, 4, 12, 12, '#C89478', '#B88468'],
  [-10, -52, 4, 12, 9, '#E8E4E0', '#D8D4D0'],
  [-14, -52, 4, 12, 12, '#F0C4BE', '#E8B5B0'],
  [-18, -52, 4, 12, 9, '#D4A09A', '#C89488'],
  [42, -52, 4, 12, 9, '#F5E6C8', '#E8D5B0'],
  [46, -52, 4, 12, 12, '#B5D4E8', '#A0C4D8'],
] as const

export const W2_MIDRISE_BUILDINGS: readonly World2MidRiseSpec[] = [
  [55, 45, 16, 14, 24, '#466291', '#5A76A5'],
  [-55, -50, 14, 14, 21, '#374E76', '#4B628A'],
  [50, -50, 14, 14, 30, '#303E52', '#445266'],
  [-55, 45, 16, 14, 21, '#52769E', '#668AB2'],
  [60, 0, 14, 16, 15, '#A86C48', '#B9805A'],
  [-60, 0, 14, 16, 18, '#34486E', '#485C82'],
  [0, 60, 18, 14, 18, '#768A98', '#8A9EAC'],
  [0, -62, 16, 12, 15, '#CDBEA0', '#DACDAF'],
  [65, 25, 12, 12, 18, '#94483E', '#A55A4E'],
  [-65, -25, 10, 12, 21, '#3C5070', '#506484'],
  [65, -25, 12, 12, 15, '#628E73', '#76A287'],
  [-65, 25, 12, 10, 15, '#B2946E', '#C3A580'],
  [75, 0, 10, 10, 12, '#C6B696', '#D4C6A8'],
  [-75, 0, 10, 10, 12, '#B2AFA5', '#C0BEB4'],
] as const

export const W2_TREE_POSITIONS: readonly World2TreePos[] = [
  [-38, 5], [-30, 5], [-6, 5], [22, 5], [30, 5], [38, 5],
  [-38, -5], [-30, -5], [-6, -5], [22, -5], [30, -5], [38, -5],
  [5, -38], [5, -30], [5, 38],
  [-5, -38], [-5, -30], [-5, 38],
  [-20, 43], [-10, 43], [10, 43], [20, 43], [30, 43],
  [-20, -47], [-10, -47], [10, -47], [20, -47],
  [47, -12], [47, 0], [47, 12],
  [-47, -12], [-47, 0], [-47, 12],
  [-6, 64], [0, 66], [6, 64],
  [64, -6], [66, 0], [64, 6],
  [-70, 20], [-70, -20], [70, 20], [70, -20],
  [0, 78], [0, -78],
] as const

export const W2_PARKS: readonly World2ParkRect[] = [
  [0, 66, 18, 10],
  [65, 0, 10, 18],
  [-65, 40, 8, 8],
  [0, -70, 14, 8],
] as const

export function world2RoadStrips(span: number): readonly World2RoadStrip[] {
  return [
    [0, 0, span, 8],
    [0, 0, 8, span],
    [0, -45, span, 5],
    [0, 45, span, 5],
    [-45, 0, 5, span],
    [45, 0, 5, span],
  ] as const
}

export function world2LaneStrips(span: number): readonly World2RoadStrip[] {
  return [
    [0, 0, span, 0.14],
    [0, 0, 0.14, span],
  ] as const
}

export function world2ShophouseSpecs() {
  return W2_SHOPHOUSES.map(([cx, cz, w, d, h, bodyColor, roofColor]) => ({
    cx, cz, w, d, h, bodyColor, roofColor,
  }))
}

export function world2MidRiseSpecs() {
  return W2_MIDRISE_BUILDINGS.map(([cx, cz, w, d, h, bodyColor, roofColor]) => ({
    cx, cz, w, d, h, bodyColor, roofColor,
  }))
}
