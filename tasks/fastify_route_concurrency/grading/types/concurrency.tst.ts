// Hidden type test. Uses only the public surface the prompt names:
// the `concurrency` route option, the `concurrency` register option and
// `request.routeOptions.concurrency`. No exported type names are imported,
// so any declaration shape that satisfies the prompt passes.
import { expect } from 'tstyche'
import fastify, { FastifyInstance, FastifyRequest } from 'FASTIFY_ROOT/fastify.js'

const app = fastify()
const handler = async () => 'ok'

// Route option: full and minimal shapes compile.
expect(app.get('/full', { concurrency: { max: 2, queueLimit: 10, queueTimeout: 5000 } }, handler)).type.toBe<FastifyInstance>()
expect(app.get('/min', { concurrency: { max: 1 } }, handler)).type.toBe<FastifyInstance>()
expect(app.route({ method: 'GET', url: '/r', concurrency: { max: 1 }, handler })).type.toBe<FastifyInstance>()

// Route option: wrong field types and a missing `max` are rejected.
expect(app.get).type.not.toBeCallableWith('/bad-max', { concurrency: { max: '2' } }, handler)
expect(app.get).type.not.toBeCallableWith('/bad-queue', { concurrency: { max: 1, queueLimit: '10' } }, handler)
expect(app.get).type.not.toBeCallableWith('/bad-timeout', { concurrency: { max: 1, queueTimeout: true } }, handler)
expect(app.get).type.not.toBeCallableWith('/no-max', { concurrency: { queueLimit: 1 } }, handler)

// Plugin registration option: same shape accepted, wrong field type rejected.
const plugin = async function (instance: FastifyInstance) {}
expect(app.register).type.toBeCallableWith(plugin, { prefix: '/p', concurrency: { max: 2, queueLimit: 10 } })
expect(app.register).type.not.toBeCallableWith(plugin, { concurrency: { max: '2' } })

// request.routeOptions.concurrency: the normalized three-field object, or undefined.
declare const request: FastifyRequest
expect(request.routeOptions).type.toHaveProperty('concurrency')
const resolved = request.routeOptions.concurrency
if (resolved !== undefined) {
  expect(resolved.max).type.toBe<number>()
  expect(resolved.queueLimit).type.toBe<number>()
  expect(resolved.queueTimeout).type.toBe<number>()
}
expect<undefined>().type.toBeAssignableTo<typeof request.routeOptions.concurrency>()
