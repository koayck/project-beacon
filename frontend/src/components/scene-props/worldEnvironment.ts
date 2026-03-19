import { z } from 'zod'
import type { MidRiseSpec } from './MidRise'
import type { ShophouseSpec } from './Shophouses'

const Hex = z.string().regex(/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/)
const tuple2 = z.tuple([z.number(), z.number()])
const tuple3 = z.tuple([z.number(), z.number(), z.number()])
const tuple4 = z.tuple([z.number(), z.number(), z.number(), z.number()])

const EnvironmentSchema = z.object({
  colors: z.object({
    road: Hex,
    line: Hex,
    park: Hex,
    trunk: Hex,
    leaf: Hex,
    canal: Hex,
  }),
  roads: z.object({
    strips: z.array(tuple4),
    lane_strips: z.array(tuple4),
  }),
  canal: z.object({
    position: tuple3,
    width: z.number().positive(),
    opacity: z.number().min(0).max(1),
  }),
  parks: z.array(tuple4),
  trees: z.object({
    positions: z.array(tuple2),
    trunk_size: tuple3,
    leaf_radius: z.number().positive(),
    trunk_y: z.number(),
    leaf_y: z.number(),
  }),
  decor_buildings: z.array(
    z.object({
      type: z.string().min(1),
      cx: z.number(),
      cz: z.number(),
      w: z.number().positive(),
      d: z.number().positive(),
      h: z.number().positive(),
      body_color: Hex,
      roof_color: Hex,
    }),
  ),
})

const WorldFileSchema = z.object({
  environment: EnvironmentSchema,
})

type EnvironmentInput = z.infer<typeof EnvironmentSchema>

export interface ResolvedWorldEnvironment {
  colors: Readonly<{
    road: string
    line: string
    park: string
    trunk: string
    leaf: string
    canal: string
  }>
  roads: Readonly<{
    strips: readonly (readonly [number, number, number, number])[]
    lane_strips: readonly (readonly [number, number, number, number])[]
  }>
  canal: Readonly<{
    position: readonly [number, number, number]
    width: number
    opacity: number
  }>
  parks: readonly (readonly [number, number, number, number])[]
  trees: Readonly<{
    positions: readonly (readonly [number, number])[]
    trunk_size: readonly [number, number, number]
    leaf_radius: number
    trunk_y: number
    leaf_y: number
  }>
  shophouseSpecs: readonly ShophouseSpec[]
  midRiseSpecs: readonly MidRiseSpec[]
}

function resolveEnvironment(env: EnvironmentInput): ResolvedWorldEnvironment {
  const shophouseSpecs: ShophouseSpec[] = []
  const midRiseSpecs: MidRiseSpec[] = []

  for (const b of env.decor_buildings) {
    const spec = {
      cx: b.cx,
      cz: b.cz,
      w: b.w,
      d: b.d,
      h: b.h,
      bodyColor: b.body_color,
      roofColor: b.roof_color,
    }

    if (b.type === 'shophouse') shophouseSpecs.push(spec)
    else if (b.type === 'midrise' || b.type === 'tower') midRiseSpecs.push(spec)
    else {
      throw new Error(
        `Unsupported decor_buildings.type "${b.type}". Supported types: shophouse, midrise, tower.`,
      )
    }
  }

  return {
    colors: env.colors,
    roads: env.roads,
    canal: env.canal,
    parks: env.parks,
    trees: env.trees,
    shophouseSpecs,
    midRiseSpecs,
  }
}

export function parseWorldEnvironmentFromFile(json: unknown): ResolvedWorldEnvironment {
  const parsed = WorldFileSchema.parse(json)
  return resolveEnvironment(parsed.environment)
}

export async function loadWorldEnvironmentFromUrl(url: string): Promise<ResolvedWorldEnvironment> {
  const response = await fetch(url, { cache: 'no-store' })
  if (!response.ok) {
    throw new Error(`Failed to load world file from ${url} (${response.status})`)
  }
  const json = await response.json()
  return parseWorldEnvironmentFromFile(json)
}
