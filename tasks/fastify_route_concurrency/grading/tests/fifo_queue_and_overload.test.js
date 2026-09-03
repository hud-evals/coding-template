'use strict'

const { test } = require('node:test')
const assert = require('node:assert/strict')
const http = require('node:http')
const { Fastify, deferred, delay, waitFor, expectPrompt } = require('./helpers.cjs')

test('queued requests enter the route lifecycle in strict FIFO order', async t => {
  const app = Fastify()
  const gate = deferred()
  t.after(() => gate.resolve())
  const started = []

  app.get('/:id', {
    concurrency: { max: 1, queueLimit: 5, queueTimeout: 2000 }
  }, async request => {
    started.push(request.params.id)
    if (request.params.id === 'first') await gate.promise
    return request.params.id
  })

  const first = app.inject('/first')
  await waitFor(() => started.length === 1, 500)
  const second = app.inject('/second')
  const third = app.inject('/third')
  const fourth = app.inject('/fourth')

  await delay(25)
  const beforeRelease = [...started]
  gate.resolve()
  const responses = await Promise.all([first, second, third, fourth])

  assert.deepEqual(beforeRelease, ['first'])
  assert.deepEqual(started, ['first', 'second', 'third', 'fourth'])
  assert.deepEqual(responses.map(response => response.payload), ['first', 'second', 'third', 'fourth'])
})

test('queueLimit: 0 immediately rejects excess requests without queueing', async t => {
  const app = Fastify()
  const gate = deferred()
  t.after(() => gate.resolve())
  let running = 0

  app.get('/no-queue', {
    concurrency: { max: 1, queueLimit: 0 }
  }, async () => {
    running++
    if (running > 1) return 'excess-admitted'
    await gate.promise
    return 'ok'
  })

  const req1 = app.inject('/no-queue')
  await waitFor(() => running === 1, 500)
  const req2 = await expectPrompt(app.inject('/no-queue'), 1000, 'excess request with queueLimit: 0')

  assert.equal(req2.statusCode, 503)
  assert.equal(req2.json().code, 'FST_ERR_ROUTE_CONCURRENCY_QUEUE_FULL')

  gate.resolve()
  const res1 = await req1
  assert.equal(res1.statusCode, 200)
})

test('full queue rejects with 503 FST_ERR_ROUTE_CONCURRENCY_QUEUE_FULL without entering hooks or handler', async t => {
  const app = Fastify()
  const gate = deferred()
  t.after(() => gate.resolve())
  const entered = []

  app.get('/:id', {
    concurrency: { max: 1, queueLimit: 1, queueTimeout: 2000 },
    onRequest: async request => {
      entered.push(`hook:${request.params.id}`)
    }
  }, async request => {
    entered.push(`handler:${request.params.id}`)
    if (request.params.id === 'hold') await gate.promise
    return request.params.id
  })

  const held = app.inject('/hold')
  await waitFor(() => entered.includes('handler:hold'), 500)
  const queued = app.inject('/queued')
  await delay(10)
  const rejected = await expectPrompt(app.inject('/rejected'), 1000, 'request arriving at a full queue')

  assert.equal(rejected.statusCode, 503)
  assert.equal(rejected.json().code, 'FST_ERR_ROUTE_CONCURRENCY_QUEUE_FULL')
  assert.equal(entered.includes('hook:rejected'), false)
  assert.equal(entered.includes('handler:rejected'), false)

  gate.resolve()
  await Promise.all([held, queued])
})

test('queue expiry returns 503 FST_ERR_ROUTE_CONCURRENCY_QUEUE_TIMEOUT without entering hooks or handler', async t => {
  const app = Fastify()
  const gate = deferred()
  t.after(() => gate.resolve())
  const entered = []

  app.get('/:id', {
    concurrency: { max: 1, queueLimit: 1, queueTimeout: 40 },
    onRequest: async request => {
      entered.push(`hook:${request.params.id}`)
    }
  }, async request => {
    entered.push(`handler:${request.params.id}`)
    if (request.params.id === 'hold') await gate.promise
    return request.params.id
  })

  const held = app.inject('/hold')
  await waitFor(() => entered.includes('handler:hold'), 500)
  const expired = await expectPrompt(app.inject('/expired'), 1500, 'queued request with queueTimeout: 40')

  assert.equal(expired.statusCode, 503)
  assert.equal(expired.json().code, 'FST_ERR_ROUTE_CONCURRENCY_QUEUE_TIMEOUT')
  assert.equal(entered.includes('hook:expired'), false)
  assert.equal(entered.includes('handler:expired'), false)

  gate.resolve()
  await held
})

test('mid-queue cancellations preserve strict FIFO order for remaining requests', async t => {
  const app = Fastify()
  const gate = deferred()
  t.after(() => gate.resolve())
  const executed = []

  app.get('/:id', {
    concurrency: { max: 1, queueLimit: 10, queueTimeout: 5000 }
  }, async request => {
    executed.push(request.params.id)
    if (request.params.id === 'root') await gate.promise
    return request.params.id
  })

  await app.listen({ port: 0 })
  t.after(() => app.close())
  const port = app.server.address().port

  function makeReq (path) {
    let raw
    const promise = new Promise(resolve => {
      raw = http.get({ port, path }, res => {
        res.resume()
        res.on('end', () => resolve({ path, statusCode: res.statusCode }))
      })
      raw.on('error', error => resolve({ path, error }))
    })
    return { get raw () { return raw }, promise }
  }

  const rootReq = makeReq('/root')
  await waitFor(() => executed.includes('root'), 500)

  const reqs = ['q1', 'q2', 'q3', 'q4', 'q5'].map(id => makeReq(`/${id}`))
  await delay(20)

  reqs[1].raw.destroy()
  reqs[3].raw.destroy()
  await delay(20)

  gate.resolve()
  await rootReq.promise
  await Promise.all(reqs.map(r => r.promise))

  assert.deepEqual(executed, ['root', 'q1', 'q3', 'q5'])
})

test('simultaneous queue timeout race conditions properly bypass expired waiters', async t => {
  const app = Fastify()
  const gate = deferred()
  t.after(() => gate.resolve())
  const executed = []

  app.get('/:id', {
    concurrency: { max: 1, queueLimit: 5, queueTimeout: 35 }
  }, async request => {
    executed.push(request.params.id)
    if (request.params.id === 'root') await gate.promise
    return request.params.id
  })

  const root = app.inject('/root')
  await waitFor(() => executed.includes('root'), 500)

  const req1 = app.inject('/timeout-1')
  const req2 = app.inject('/timeout-2')
  await delay(50) // both expire

  const req3 = app.inject('/live-3')
  await delay(10)

  gate.resolve()
  const [resRoot, res1, res2, res3] = await Promise.all([root, req1, req2, req3])

  assert.equal(resRoot.statusCode, 200)
  assert.equal(res1.statusCode, 503)
  assert.equal(res1.json().code, 'FST_ERR_ROUTE_CONCURRENCY_QUEUE_TIMEOUT')
  assert.equal(res2.statusCode, 503)
  assert.equal(res2.json().code, 'FST_ERR_ROUTE_CONCURRENCY_QUEUE_TIMEOUT')
  assert.equal(res3.statusCode, 200)
  assert.deepEqual(executed, ['root', 'live-3'])
})
