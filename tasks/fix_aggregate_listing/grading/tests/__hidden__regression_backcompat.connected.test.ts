/**
 * Hidden grading tests — back-compat and regression safety (connected).
 *
 *   1. The unsharded cursor format is unchanged: the returned cursor still
 *      decodes as base64(JSON of the raw LastEvaluatedKey).
 *   2. A legacy-format unsharded cursor (base64 raw LastEvaluatedKey JSON,
 *      constructed by hand exactly as a deployed client would hold it) is
 *      accepted and resumes at the right position.
 *   3. One- and many-edge children stay fully assembled in listed pages,
 *      unsharded and sharded.
 *
 * Assumes DynamoDB Local at DYNAMODB_ENDPOINT (default http://localhost:8000).
 */

import { it } from "@effect/vitest"
import { Effect, Layer, Schema } from "effect"
import { afterAll, beforeAll, describe, expect } from "vitest"

import * as DynamoSchema from "@effect-dynamodb/schema/DynamoSchema.js"
import * as Aggregate from "../src/Aggregate.js"
import { DynamoClient } from "../src/DynamoClient.js"
import * as Entity from "../src/Entity.js"
import * as Table from "../src/Table.js"

const ENDPOINT = process.env.DYNAMODB_ENDPOINT ?? "http://localhost:8000"

class Part extends Schema.Class<Part>("Part")({
  id: Schema.String,
  label: Schema.String,
}) {}

class SpecInfo extends Schema.Class<SpecInfo>("SpecInfo")({
  material: Schema.String,
}) {}

class Reg extends Schema.Class<Reg>("Reg")({
  id: Schema.String,
  name: Schema.String,
  spec: SpecInfo,
  parts: Schema.Array(Part),
}) {}

class Owner extends Schema.Class<Owner>("Owner")({
  id: Schema.String,
}) {}

const GSchema = DynamoSchema.make({ name: "gpack", version: 1, casing: "preserve" })
const tableName = `hidden-reg-${Date.now()}`

const Owners = Entity.make({
  model: Owner,
  entityType: "regowner",
  primaryKey: {
    pk: { field: "pk", composite: ["id"] },
    sk: { field: "sk", composite: [] },
  },
})

const RegTable = Table.make({ schema: GSchema, entities: { Owners } })

const RegAggregate = Aggregate.make(Reg, {
  table: RegTable,
  schema: GSchema,
  pk: { field: "pk", composite: ["id"] },
  collection: { index: "lsiR", name: "reg", sk: { field: "lsiRsk", composite: [] } },
  list: {
    index: "gsiR",
    name: "reglist",
    pk: { field: "gsiRpk", composite: [] },
    sk: { field: "gsiRsk", composite: ["name"] },
  },
  root: { entityType: "regroot" },
  edges: {
    spec: Aggregate.one("spec", { entityType: "regspec" }),
    parts: Aggregate.many("parts", { entityType: "regpart" }),
  },
})

const HotRegAggregate = Aggregate.make(Reg, {
  table: RegTable,
  schema: GSchema,
  pk: { field: "pk", composite: ["id"] },
  collection: { index: "lsiHR", name: "hotreg", sk: { field: "lsiHRsk", composite: [] } },
  list: {
    index: "gsiHR",
    name: "hotreglist",
    pk: { field: "gsiHRpk", composite: [] },
    sk: { field: "gsiHRsk", composite: ["name"] },
    cardinality: 3,
  },
  root: { entityType: "hotregroot" },
  edges: {
    spec: Aggregate.one("spec", { entityType: "hotregspec" }),
    parts: Aggregate.many("parts", { entityType: "hotregpart" }),
  },
})

const ClientLayer = DynamoClient.layer({
  region: "us-east-1",
  endpoint: ENDPOINT,
  credentials: { accessKeyId: "local", secretAccessKey: "local" },
})
const TestLayer = Layer.mergeAll(ClientLayer, RegTable.layer({ name: tableName }))
const provide = Effect.provide(TestLayer)

const ids = Array.from({ length: 8 }, (_, i) => `r-${i + 1}`)
const nameOf = (id: string) => `name-${id.slice(2)}` // name-1 .. name-8

// Raw LastEvaluatedKey exactly as the pre-existing unsharded cursor codec
// stores it: GSI pk/sk plus the table pk/sk, in AttributeValue JSON form.
const rawKeyAfter = (id: string) => ({
  gsiRpk: { S: "$gpack#v1#reglist" },
  gsiRsk: { S: `$gpack#v1#reglist#${nameOf(id)}` },
  pk: { S: `$gpack#v1#reg#${id}` },
  sk: { S: "$gpack#v1#regroot" },
})

describe("hidden: cursor back-compat + edge assembly", () => {
  beforeAll(async () => {
    await Effect.runPromise(
      Effect.gen(function* () {
        const db = yield* DynamoClient.make({
          entities: { Owners },
          aggregates: { RegAggregate, HotRegAggregate },
          tables: { RegTable },
        })
        yield* db.tables.RegTable.create()
        for (const id of ids) {
          const input = {
            id,
            name: nameOf(id),
            spec: { material: `steel-${id}` },
            parts: [
              { id: `${id}-p1`, label: `${id} north` },
              { id: `${id}-p2`, label: `${id} south` },
            ],
          }
          yield* RegAggregate.create(input)
          yield* HotRegAggregate.create(input)
        }
      }).pipe(provide, Effect.scoped),
    )
  }, 240000)

  afterAll(async () => {
    await Effect.runPromise(
      Effect.gen(function* () {
        const client = yield* DynamoClient
        yield* client.deleteTable({ TableName: tableName })
      }).pipe(
        provide,
        Effect.scoped,
        Effect.ignore,  // teardown best-effort (Effect v4: catchAll was removed)
      ),
    )
  }, 30000)

  it.effect("unsharded cursor still decodes as the raw LastEvaluatedKey JSON", () =>
    Effect.gen(function* () {
      const page = yield* RegAggregate.list(undefined, { limit: 3 })
      expect(page.data.map((r) => r.id)).toEqual(["r-1", "r-2", "r-3"])
      expect(page.cursor).not.toBeNull()
      const decoded = JSON.parse(atob(page.cursor!))
      expect(decoded).toEqual(rawKeyAfter("r-3"))
    }).pipe(provide),
  )

  it.effect("accepts a legacy cursor built as base64 raw LastEvaluatedKey JSON", () =>
    Effect.gen(function* () {
      // Constructed by hand — this is exactly what a deployed client that
      // paginated before this release still holds.
      const legacyCursor = btoa(JSON.stringify(rawKeyAfter("r-3")))
      const page = yield* RegAggregate.list(undefined, { limit: 3, cursor: legacyCursor })
      expect(page.data.map((r) => r.id)).toEqual(["r-4", "r-5", "r-6"])
    }).pipe(provide),
  )

  it.effect("legacy-format cursors chain to exhaustion without skips or dups", () =>
    Effect.gen(function* () {
      const pages: Array<Array<string>> = []
      let cursor: string | undefined
      let guard = 0
      do {
        const page = yield* RegAggregate.list(undefined, { limit: 3, cursor })
        pages.push(page.data.map((r) => r.id))
        cursor = page.cursor ?? undefined
        guard += 1
        expect(guard).toBeLessThan(20)
      } while (cursor !== undefined)
      while (pages.length > 0 && pages[pages.length - 1]!.length === 0) pages.pop()
      expect(pages.map((p) => p.length)).toEqual([3, 3, 2])
      expect(pages.flat()).toEqual(ids)
    }).pipe(provide),
  )

  it.effect("one- and many-edge children stay assembled in unsharded pages", () =>
    Effect.gen(function* () {
      const page = yield* RegAggregate.list(undefined, { limit: 4 })
      expect(page.data).toHaveLength(4)
      for (const reg of page.data) {
        expect(reg.spec.material).toBe(`steel-${reg.id}`)
        expect(reg.parts.map((p) => p.label).sort()).toEqual([
          `${reg.id} north`,
          `${reg.id} south`,
        ])
      }
    }).pipe(provide),
  )

  it.effect("one- and many-edge children stay assembled across a sharded walk", () =>
    Effect.gen(function* () {
      const seen: Array<string> = []
      let cursor: string | undefined
      let guard = 0
      do {
        const page = yield* HotRegAggregate.list(undefined, { limit: 2, cursor })
        for (const reg of page.data) {
          seen.push(reg.id)
          expect(reg.spec.material).toBe(`steel-${reg.id}`)
          expect(reg.parts.map((p) => p.label).sort()).toEqual([
            `${reg.id} north`,
            `${reg.id} south`,
          ])
        }
        cursor = page.cursor ?? undefined
        guard += 1
        expect(guard).toBeLessThan(20)
      } while (cursor !== undefined)
      expect(seen.sort()).toEqual([...ids].sort())
    }).pipe(provide),
  )
})
