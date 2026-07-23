/**
 * Hidden grading tests — throughput discipline (instrumented mock).
 *
 * Max-in-flight probes against a mock DynamoClient:
 *   - per-page assembly must overlap (parallel) but must NOT reach the full
 *     page size simultaneously (bounded);
 *   - sharded fan-out must query every shard without a full simultaneous
 *     burst across a wide cardinality.
 *
 * A static source scan for `concurrency: "unbounded"` runs separately in the
 * grading script.
 */

import { describe, expect, it } from "@effect/vitest"
import { Effect, Layer, Schema } from "effect"
import { beforeEach, vi } from "vitest"

import * as DynamoSchema from "@effect-dynamodb/schema/DynamoSchema.js"
import { DynamoError } from "@effect-dynamodb/schema/Errors.js"
import * as Aggregate from "../src/Aggregate.js"
import { DynamoClient } from "../src/DynamoClient.js"
import * as Entity from "../src/Entity.js"
import { toAttributeMap } from "../src/Marshaller.js"
import * as Table from "../src/Table.js"

class Doc extends Schema.Class<Doc>("Doc")({
  id: Schema.String,
  title: Schema.String,
}) {}

const PSchema = DynamoSchema.make({ name: "gprobe", version: 1 })

const DocOwners = Entity.make({
  model: Doc,
  entityType: "DocOwner",
  primaryKey: {
    pk: { field: "pk", composite: ["id"] },
    sk: { field: "sk", composite: [] },
  },
})

const ProbeTable = Table.make({ schema: PSchema, entities: { DocOwners } })

const mockQuery = vi.fn()

const MockDynamoClient = Layer.succeed(DynamoClient, {
  scan: () => Effect.die("not used"),
  query: (input) =>
    Effect.tryPromise({
      try: () => mockQuery(input),
      catch: (e) => new DynamoError({ operation: "Query", cause: e }),
    }),
  putItem: () => Effect.die("not used"),
  getItem: () => Effect.die("not used"),
  deleteItem: () => Effect.die("not used"),
  updateItem: () => Effect.die("not used"),
  batchGetItem: () => Effect.die("not used"),
  batchWriteItem: () => Effect.die("not used"),
  transactGetItems: () => Effect.die("not used"),
  transactWriteItems: () => Effect.die("not used"),
  createTable: () => Effect.die("not used"),
  deleteTable: () => Effect.die("not used"),
  describeTable: () => Effect.die("not used"),
})

const ProbeLayer = Layer.merge(MockDynamoClient, ProbeTable.layer({ name: "probe-table" }))

const DocAggregate = Aggregate.make(Doc, {
  table: ProbeTable,
  schema: PSchema,
  pk: { field: "pk", composite: ["id"] },
  collection: { index: "lsi1", name: "doc", sk: { field: "lsi1sk", composite: [] } },
  list: {
    index: "gsi1",
    name: "doclist",
    pk: { field: "gsi1pk", composite: [] },
    sk: { field: "gsi1sk", composite: ["title"] },
  },
  root: { entityType: "DocRoot" },
  edges: {},
})

const WideDocAggregate = Aggregate.make(Doc, {
  table: ProbeTable,
  schema: PSchema,
  pk: { field: "pk", composite: ["id"] },
  collection: { index: "lsi2", name: "hotdoc", sk: { field: "lsi2sk", composite: [] } },
  list: {
    index: "gsi2",
    name: "hotdoclist",
    pk: { field: "gsi2pk", composite: [] },
    sk: { field: "gsi2sk", composite: ["title"] },
    cardinality: 32,
  },
  root: { entityType: "HotDocRoot" },
  edges: {},
})

const PAGE = 25

const rootItem = (id: string) =>
  toAttributeMap({
    pk: `$gprobe#v1#doc#${id}`,
    sk: "$gprobe#v1#docroot",
    gsi1pk: "$gprobe#v1#doclist",
    gsi1sk: `$gprobe#v1#doclist#${id}`,
    __edd_e__: "DocRoot",
    id,
    title: id,
  })

const partitionItem = (id: string) =>
  toAttributeMap({
    pk: `$gprobe#v1#doc#${id}`,
    sk: "$gprobe#v1#docroot",
    __edd_e__: "DocRoot",
    id,
    title: id,
  })

describe("hidden: throughput discipline probes", () => {
  beforeEach(() => {
    mockQuery.mockReset()
  })

  it.effect("page assembly overlaps but never bursts to the full page size", () =>
    Effect.gen(function* () {
      const ids = Array.from({ length: PAGE }, (_, i) => `d-${String(i).padStart(2, "0")}`)

      let inFlight = 0
      let maxInFlight = 0
      mockQuery.mockImplementation(async (input: Record<string, unknown>) => {
        if (input.IndexName === "gsi1") {
          return { Items: ids.map(rootItem) }
        }
        inFlight += 1
        maxInFlight = Math.max(maxInFlight, inFlight)
        // Hold the response one macrotask so overlap is observable.
        await new Promise((resolve) => setTimeout(resolve, 0))
        inFlight -= 1
        const pk = (input.ExpressionAttributeValues as Record<string, { S: string }>)[":pk"]!.S
        return { Items: [partitionItem(pk.slice("$gprobe#v1#doc#".length))] }
      })

      const results = yield* DocAggregate.list()

      expect(results.data).toHaveLength(PAGE)
      // Parallelized: partition queries overlap.
      expect(maxInFlight).toBeGreaterThan(1)
      // Bounded: never the whole page in flight simultaneously.
      expect(maxInFlight).toBeLessThan(PAGE)
    }).pipe(Effect.provide(ProbeLayer)),
  )

  it.effect("shard fan-out queries every shard without a full simultaneous burst", () =>
    Effect.gen(function* () {
      let inFlight = 0
      let maxInFlight = 0
      mockQuery.mockImplementation(async () => {
        inFlight += 1
        maxInFlight = Math.max(maxInFlight, inFlight)
        await new Promise((resolve) => setTimeout(resolve, 0))
        inFlight -= 1
        return { Items: [] }
      })

      const results = yield* WideDocAggregate.list()

      expect(results.data).toHaveLength(0)
      expect(results.cursor).toBeNull()
      // Every one of the 32 shards was queried...
      expect(mockQuery).toHaveBeenCalledTimes(32)
      // ...but never all at once.
      expect(maxInFlight).toBeLessThan(32)
    }).pipe(Effect.provide(ProbeLayer)),
  )
})
