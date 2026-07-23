/**
 * Hidden grading tests — sharded pagination invariants (connected).
 *
 * Fixture: 24 widgets whose list-SK order is name-w-01 .. name-w-24, written
 * into an unsharded control collection and a cardinality-3 sharded collection.
 * The djb2 hash distribution of the ids over 3 shards interleaves, and with
 * limit 5 every page boundary truncates mid-shard (verified by the fixture
 * sanity test below from ground truth, not assumed).
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

class Widget extends Schema.Class<Widget>("Widget")({
  id: Schema.String,
  name: Schema.String,
  parts: Schema.Array(Part),
}) {}

class Owner extends Schema.Class<Owner>("Owner")({
  id: Schema.String,
}) {}

const GSchema = DynamoSchema.make({ name: "gpack", version: 1, casing: "preserve" })
const tableName = `hidden-pag-${Date.now()}`

const Owners = Entity.make({
  model: Owner,
  entityType: "pagowner",
  primaryKey: {
    pk: { field: "pk", composite: ["id"] },
    sk: { field: "sk", composite: [] },
  },
})

const PagTable = Table.make({ schema: GSchema, entities: { Owners } })

// Unsharded control collection
const WidgetAggregate = Aggregate.make(Widget, {
  table: PagTable,
  schema: GSchema,
  pk: { field: "pk", composite: ["id"] },
  collection: { index: "lsiW", name: "widget", sk: { field: "lsiWsk", composite: [] } },
  list: {
    index: "gsiW",
    name: "widgetlist",
    pk: { field: "gsiWpk", composite: [] },
    sk: { field: "gsiWsk", composite: ["name"] },
  },
  root: { entityType: "widgetroot" },
  edges: {
    parts: Aggregate.many("parts", { entityType: "widgetpart" }),
  },
})

// Sharded collection — same domain data spread over 3 shards
const HotWidgetAggregate = Aggregate.make(Widget, {
  table: PagTable,
  schema: GSchema,
  pk: { field: "pk", composite: ["id"] },
  collection: { index: "lsiH", name: "hotwidget", sk: { field: "lsiHsk", composite: [] } },
  list: {
    index: "gsiH",
    name: "hotwidgetlist",
    pk: { field: "gsiHpk", composite: [] },
    sk: { field: "gsiHsk", composite: ["name"] },
    cardinality: 3,
  },
  root: { entityType: "hotwidgetroot" },
  edges: {
    parts: Aggregate.many("parts", { entityType: "hotwidgetpart" }),
  },
})

const ClientLayer = DynamoClient.layer({
  region: "us-east-1",
  endpoint: ENDPOINT,
  credentials: { accessKeyId: "local", secretAccessKey: "local" },
})
const TestLayer = Layer.mergeAll(ClientLayer, PagTable.layer({ name: tableName }))
const provide = Effect.provide(TestLayer)

const LIMIT = 5
const ids = Array.from({ length: 24 }, (_, i) => `w-${String(i + 1).padStart(2, "0")}`)
const nameOf = (id: string) => `name-${id}`
const expectedOrder = [...ids] // names ascend exactly like ids

type Lister = {
  readonly list: (
    filter?: Record<string, unknown>,
    options?: { limit?: number; cursor?: string },
  ) => Effect.Effect<
    { data: ReadonlyArray<Widget>; cursor: string | null },
    unknown,
    unknown
  >
}

// Walk a listing to exhaustion; a trailing empty page (empty data, null
// cursor) is tolerated and dropped.
const walk = (agg: Lister, limit: number) =>
  Effect.gen(function* () {
    const pages: Array<Array<string>> = []
    let cursor: string | undefined
    let guard = 0
    do {
      const page = yield* agg.list(undefined, { limit, cursor })
      expect(page.data.length).toBeLessThanOrEqual(limit)
      pages.push(page.data.map((w) => w.id))
      cursor = page.cursor ?? undefined
      guard += 1
      expect(guard).toBeLessThan(50) // runaway-cursor guard
    } while (cursor !== undefined)
    while (pages.length > 0 && pages[pages.length - 1]!.length === 0) pages.pop()
    return pages
  })

describe("hidden: sharded pagination invariants", () => {
  beforeAll(async () => {
    await Effect.runPromise(
      Effect.gen(function* () {
        const db = yield* DynamoClient.make({
          entities: { Owners },
          aggregates: { WidgetAggregate, HotWidgetAggregate },
          tables: { PagTable },
        })
        yield* db.tables.PagTable.create()
        for (const id of ids) {
          const input = {
            id,
            name: nameOf(id),
            parts: [
              { id: `${id}-p1`, label: `${id} alpha` },
              { id: `${id}-p2`, label: `${id} beta` },
            ],
          }
          yield* WidgetAggregate.create(input)
          yield* HotWidgetAggregate.create(input)
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

  it.effect("fixture sanity: 3 populated shards and every page boundary cuts mid-shard", () =>
    Effect.gen(function* () {
      const client = yield* DynamoClient
      // Ground truth straight from DynamoDB: which ids live in which shard.
      const shardIds: Array<Set<string>> = []
      for (const shard of [0, 1, 2]) {
        const res = yield* client.query({
          TableName: tableName,
          IndexName: "gsiH",
          KeyConditionExpression: "#pk = :pk",
          ExpressionAttributeNames: { "#pk": "gsiHpk" },
          ExpressionAttributeValues: {
            ":pk": { S: `$gpack#v1#hotwidgetlist#${shard}` },
          },
        })
        shardIds.push(
          new Set((res.Items ?? []).map((item) => (item.id as { S: string }).S)),
        )
      }
      for (const members of shardIds) expect(members.size).toBeGreaterThan(0)
      expect(shardIds.reduce((n, s) => n + s.size, 0)).toBe(ids.length)

      // At every page boundary (limit 5), at least one shard both contributed
      // to the page and still has items after the boundary — i.e. the
      // boundary truncates mid-shard.
      for (const boundary of [5, 10, 15, 20]) {
        const page = expectedOrder.slice(boundary - LIMIT, boundary)
        const rest = expectedOrder.slice(boundary)
        const cut = shardIds.some(
          (members) =>
            page.some((id) => members.has(id)) && rest.some((id) => members.has(id)),
        )
        expect(cut).toBe(true)
      }
    }).pipe(provide),
  )

  it.effect("sharded walk matches the unsharded control page-for-page", () =>
    Effect.gen(function* () {
      const controlPages = yield* walk(WidgetAggregate as unknown as Lister, LIMIT)
      const shardedPages = yield* walk(HotWidgetAggregate as unknown as Lister, LIMIT)

      // Page size honored until exhaustion, exactly like the control.
      expect(controlPages.map((p) => p.length)).toEqual([5, 5, 5, 5, 4])
      // Per-page set AND order equality against the control.
      expect(shardedPages).toEqual(controlPages)
      // Full-walk coverage: nothing skipped, nothing duplicated.
      const flat = shardedPages.flat()
      expect(flat).toHaveLength(ids.length)
      expect(new Set(flat).size).toBe(ids.length)
      expect(flat).toEqual(expectedOrder)
    }).pipe(provide),
  )

  it.effect("walk is deterministic across repeats", () =>
    Effect.gen(function* () {
      const first = yield* walk(HotWidgetAggregate as unknown as Lister, LIMIT)
      const second = yield* walk(HotWidgetAggregate as unknown as Lister, LIMIT)
      expect(second).toEqual(first)
    }).pipe(provide),
  )

  it.effect("no-limit sharded listing equals the control exactly, cursor null", () =>
    Effect.gen(function* () {
      const control = yield* WidgetAggregate.list()
      const sharded = yield* HotWidgetAggregate.list()
      expect(control.cursor).toBeNull()
      expect(sharded.cursor).toBeNull()
      expect(control.data.map((w) => w.id)).toEqual(expectedOrder)
      expect(sharded.data.map((w) => w.id)).toEqual(control.data.map((w) => w.id))
    }).pipe(provide),
  )

  it.effect("edge children stay fully assembled on every page of the sharded walk", () =>
    Effect.gen(function* () {
      let cursor: string | undefined
      let guard = 0
      do {
        const page = yield* HotWidgetAggregate.list(undefined, { limit: LIMIT, cursor })
        for (const widget of page.data) {
          expect(widget.parts.map((p) => p.label).sort()).toEqual([
            `${widget.id} alpha`,
            `${widget.id} beta`,
          ])
        }
        cursor = page.cursor ?? undefined
        guard += 1
        expect(guard).toBeLessThan(50)
      } while (cursor !== undefined)
    }).pipe(provide),
  )
})
