/**
 * Hidden grading tests — ordering equivalence on adversarial sort keys
 * (connected).
 *
 * Fixture names mix cases and scripts precisely where JS string comparison
 * diverges from DynamoDB's UTF-8 byte ordering:
 *   - "Bob" vs "alice": localeCompare puts alice first, bytes put Bob first
 *   - accented Latin (Ægir, émile), Greek (αθηνά)
 *   - high-BMP ligature "ﬁligree" (U+FB01) vs astral "😀grin" (U+1F600):
 *     UTF-16 code-unit comparison puts the emoji first (surrogate high
 *     0xD83D < 0xFB01), UTF-8 bytes put the ligature first.
 *
 * The unsharded control collection is the ground truth: DynamoDB itself
 * orders the control's GSI partition, so a sharded merge that matches the
 * control element-for-element matches DynamoDB byte order by construction.
 * Comparison uses full no-limit walks only — the repo's pre-existing cursor
 * codec cannot round-trip non-Latin-1 boundary keys even on unsharded lists,
 * and that pre-existing limitation is out of scope here.
 *
 * Requires the schema's `casing: "preserve"` so mixed-case values survive
 * into the list-index sort key.
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

class Exotic extends Schema.Class<Exotic>("Exotic")({
  id: Schema.String,
  name: Schema.String,
}) {}

class Owner extends Schema.Class<Owner>("Owner")({
  id: Schema.String,
}) {}

const GSchema = DynamoSchema.make({ name: "gpack", version: 1, casing: "preserve" })
const tableName = `hidden-ord-${Date.now()}`

const Owners = Entity.make({
  model: Owner,
  entityType: "ordowner",
  primaryKey: {
    pk: { field: "pk", composite: ["id"] },
    sk: { field: "sk", composite: [] },
  },
})

const OrdTable = Table.make({ schema: GSchema, entities: { Owners } })

const ExoticAggregate = Aggregate.make(Exotic, {
  table: OrdTable,
  schema: GSchema,
  pk: { field: "pk", composite: ["id"] },
  collection: { index: "lsiE", name: "exotic", sk: { field: "lsiEsk", composite: [] } },
  list: {
    index: "gsiE",
    name: "exoticlist",
    pk: { field: "gsiEpk", composite: [] },
    sk: { field: "gsiEsk", composite: ["name"] },
  },
  root: { entityType: "exoticroot" },
  edges: {},
})

const HotExoticAggregate = Aggregate.make(Exotic, {
  table: OrdTable,
  schema: GSchema,
  pk: { field: "pk", composite: ["id"] },
  collection: { index: "lsiX", name: "hotexotic", sk: { field: "lsiXsk", composite: [] } },
  list: {
    index: "gsiX",
    name: "hotexoticlist",
    pk: { field: "gsiXpk", composite: [] },
    sk: { field: "gsiXsk", composite: ["name"] },
    cardinality: 3,
  },
  root: { entityType: "hotexoticroot" },
  edges: {},
})

const ClientLayer = DynamoClient.layer({
  region: "us-east-1",
  endpoint: ENDPOINT,
  credentials: { accessKeyId: "local", secretAccessKey: "local" },
})
const TestLayer = Layer.mergeAll(ClientLayer, OrdTable.layer({ name: tableName }))
const provide = Effect.provide(TestLayer)

// Seeding order deliberately differs from every candidate sort order.
// ids e-1..e-9 hash-distribute 3/3/3 across the 3 shards.
const fixtures: ReadonlyArray<{ id: string; name: string }> = [
  { id: "e-1", name: "alice" },
  { id: "e-2", name: "\u{1F600}grin" }, // 😀grin (astral, surrogate pair)
  { id: "e-3", name: "Zoe" },
  { id: "e-4", name: "\uFB01ligree" }, // ﬁligree (high-BMP ligature)
  { id: "e-5", name: "\u00C9mile" }, // Émile
  { id: "e-6", name: "Bob" },
  { id: "e-7", name: "\u03B1\u03B8\u03B7\u03BD\u03AC" }, // αθηνά
  { id: "e-8", name: "ant" },
  { id: "e-9", name: "\u00C6gir" }, // Ægir
]

// UTF-8 byte order of the names above (== Unicode code-point order):
// B(0x42) < Z(0x5A) < a-l < a-n < U+00C6 < U+00C9 < U+03B1 < U+FB01 < U+1F600
const expectedNames = [
  "Bob",
  "Zoe",
  "alice",
  "ant",
  "\u00C6gir",
  "\u00C9mile",
  "\u03B1\u03B8\u03B7\u03BD\u03AC",
  "\uFB01ligree",
  "\u{1F600}grin",
]

describe("hidden: ordering equivalence (mixed case + non-ASCII)", () => {
  beforeAll(async () => {
    await Effect.runPromise(
      Effect.gen(function* () {
        const db = yield* DynamoClient.make({
          entities: { Owners },
          aggregates: { ExoticAggregate, HotExoticAggregate },
          tables: { OrdTable },
        })
        yield* db.tables.OrdTable.create()
        for (const item of fixtures) {
          yield* ExoticAggregate.create(item)
          yield* HotExoticAggregate.create(item)
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

  it.effect("fixture sanity: the control walks in DynamoDB UTF-8 byte order", () =>
    Effect.gen(function* () {
      const control = yield* ExoticAggregate.list()
      expect(control.cursor).toBeNull()
      expect(control.data.map((e) => e.name)).toEqual(expectedNames)
    }).pipe(provide),
  )

  it.effect("fixture sanity: every shard is populated", () =>
    Effect.gen(function* () {
      const client = yield* DynamoClient
      for (const shard of [0, 1, 2]) {
        const res = yield* client.query({
          TableName: tableName,
          IndexName: "gsiX",
          KeyConditionExpression: "#pk = :pk",
          ExpressionAttributeNames: { "#pk": "gsiXpk" },
          ExpressionAttributeValues: {
            ":pk": { S: `$gpack#v1#hotexoticlist#${shard}` },
          },
        })
        expect((res.Items ?? []).length).toBeGreaterThan(0)
      }
    }).pipe(provide),
  )

  it.effect("sharded full listing preserves the control's exact order", () =>
    Effect.gen(function* () {
      const control = yield* ExoticAggregate.list()
      const sharded = yield* HotExoticAggregate.list()
      expect(sharded.cursor).toBeNull()
      expect(sharded.data.map((e) => e.name)).toEqual(control.data.map((e) => e.name))
      expect(sharded.data.map((e) => e.id)).toEqual(control.data.map((e) => e.id))
      // Exact coverage
      expect(new Set(sharded.data.map((e) => e.id)).size).toBe(fixtures.length)
    }).pipe(provide),
  )

  it.effect("repeated sharded listings return the identical order", () =>
    Effect.gen(function* () {
      const first = yield* HotExoticAggregate.list()
      const second = yield* HotExoticAggregate.list()
      expect(second.data.map((e) => e.id)).toEqual(first.data.map((e) => e.id))
    }).pipe(provide),
  )
})
