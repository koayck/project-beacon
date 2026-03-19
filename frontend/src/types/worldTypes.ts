export type WindowFace = 'north' | 'south' | 'west' | 'east' | 'top'

export interface WorldWindowLayout {
  floor: number
  face: WindowFace
  offset: number
  width: number
  height: number
  sill: number
}

export interface WorldBalconyLayout {
  floor: number
  face: WindowFace
  depth: number
  width: number
}

export interface WorldBuilding {
  id: number
  name: string
  cx: number
  cz: number
  w: number
  d: number
  h: number
  windows: WorldWindowLayout[]
  balcony: WorldBalconyLayout | null
}

export interface SimWindowAperture {
  face: WindowFace
  axisCenter: number
  sillY: number
  width: number
  height: number
}

export interface SimBuilding {
  id: number
  name: string
  parentBuildingId?: number
  cx: number
  cz: number
  w: number
  d: number
  h: number
  minY?: number
  windows: SimWindowAperture[]
}

export interface SurvivorPoint {
  x: number
  y: number
  z: number
}
