/**
 * Hidden grading tests — N+1 fix effectiveness (instrumented mock).
 *
 * Verifies page assembly is actually parallelized (queries overlap), that
 * output stays in list-index order even when responses resolve out of order,
 * and that fail-fast error semantics are kept (one failing partition query
 * fails the whole list with the tagged error).
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

const pkOf = (input: Record<string, unknown>): string =>
  (input.ExpressionAttributeValues as Record<string, { S: string }>)[":pk"]!.S

describe("hidden: N+1 assembly probes", () => {
  beforeEach(() => {
    mockQuery.mockReset()
  })

  it.effect("partition queries for one page overlap (no serial N+1)", () =>
    Effect.gen(function* () {
      const ids = Array.from({ length: 12 }, (_, i) => `d-${String(i).padStart(2, "0")}`)

      let inFlight = 0
      let maxInFlight = 0
      mockQuery.mockImplementation(async (input: Record<string, unknown>) => {
        if (input.IndexName === "gsi1") {
          return { Items: ids.map(rootItem) }
        }
        inFlight += 1
        maxInFlight = Math.max(maxInFlight, inFlight)
        await new Promise((resolve) => setTimeout(resolve, 0))
        inFlight -= 1
        return { Items: [partitionItem(pkOf(input).slice("$gprobe#v1#doc#".length))] }
      })

      const results = yield* DocAggregate.list()

      expect(results.data).toHaveLength(12)
      expect(maxInFlight).toBeGreaterThan(1)
    }).pipe(Effect.provide(ProbeLayer)),
  )

  it.effect("output preserves list-index order when responses resolve out of order", () =>
    Effect.gen(function* () {
      mockQuery.mockImplementation(async (input: Record<string, unknown>) => {
        if (input.IndexName === "gsi1") {
          return { Items: [rootItem("d-1"), rootItem("d-2")] }
        }
        const id = pkOf(input).slice("$gprobe#v1#doc#".length)
        if (id === "d-1") {
          // First root's partition resolves last — the page must still come
          // back in list-index order, not response-arrival order.
          await new Promise((resolve) => setTimeout(resolve, 5))
        }
        return { Items: [partitionItem(id)] }
      })

      const results = yield* DocAggregate.list()

      expect(results.data.map((d) => d.id)).toEqual(["d-1", "d-2"])
    }).pipe(Effect.provide(ProbeLayer)),
  )

  it.effect("a failing partition query fails the list with the tagged error", () =>
    Effect.gen(function* () {
      mockQuery.mockImplementation(async (input: Record<string, unknown>) => {
        if (input.IndexName === "gsi1") {
          return { Items: [rootItem("d-1"), rootItem("d-2")] }
        }
        const id = pkOf(input).slice("$gprobe#v1#doc#".length)
        if (id === "d-2") {
          throw new Error("provisioned throughput exceeded")
        }
        return { Items: [partitionItem(id)] }
      })

      const error = yield* Effect.flip(DocAggregate.list())

      expect(error._tag).toBe("DynamoError")
    }).pipe(Effect.provide(ProbeLayer)),
  )
})
