'use strict'

const { test } = require('node:test')
const assert = require('node:assert/strict')
const http = require('node:http')
const { Fastify, deferred, delay, waitFor } = require('./helpers.cjs')

test('invalid concurrency options throw TypeError with code FST_ERR_ROUTE_CONCURRENCY_OPTION_INVALID', () => {
  const invalidValues = [
    null,
    [],
    {},
    { max: 0 },
    { max: -1 },
    { max: 1.5 },
    { max: '1' },
    { max: 1, queueLimit: -1 },
    { max: 1, queueLimit: 0.5 },
    { max: 1, queueLimit: '0' },
    { max: 1, queueTimeout: 0 },
    { max: 1, queueTimeout: -100 },
    { max: 1, queueTimeout: 1.5 },
    { max: 1, queueTimeout: '5000' }
  ]

  for (const concurrency of invalidValues) {
    const app = Fastify()
    assert.throws(
      () => app.get('/', { concurrency }, async () => 'ok'),
      error => error instanceof TypeError && error.code === 'FST_ERR_ROUTE_CONCURRENCY_OPTION_INVALID',
      `Expected TypeError with FST_ERR_ROUTE_CONCURRENCY_OPTION_INVALID for ${JSON.stringify(concurrency)}`
    )
  }
})

test('caps admitted active work to max and releases slots after normal responses', async t => {
  const app = Fastify()
  const gate = deferred()
  t.after(() => gate.resolve())
  const started = []
  let active = 0
  let maximum = 0

  app.get('/:id', {
    concurrency: { max: 2, queueLimit: 5, queueTimeout: 2000 }
  }, async request => {
    active++
    maximum = Math.max(maximum, active)
    started.push(request.params.id)
    await gate.promise
    active--
    return request.params.id
  })

  const requests = [app.inject('/1'), app.inject('/2'), app.inject('/3')]
  await waitFor(() => started.length >= 2, 500)
  await delay(20)
  const beforeRelease = [...started]
  gate.resolve()
  const responses = await Promise.all(requests)

  assert.deepEqual(beforeRelease, ['1', '2'])
  assert.equal(maximum, 2)
  assert.deepEqual(responses.map(response => response.statusCode), [200, 200, 200])
})

test('handler error releases slot cleanly for subsequent requests', async t => {
  const app = Fastify()
  const gate = deferred()
  t.after(() => gate.resolve())
  const started = []

  app.get('/:id', {
    concurrency: { max: 1, queueLimit: 2, queueTimeout: 2000 }
  }, async request => {
    started.push(request.params.id)
    if (request.params.id === 'fail') {
      await gate.promise
      throw new Error('expected failure')
    }
    return 'ok'
  })

  const failing = app.inject('/fail')
  await waitFor(() => started.length === 1, 500)
  const queued = app.inject('/next')
  await delay(20)
  assert.deepEqual(started, ['fail'])

  gate.resolve()
  const [failedResponse, queuedResponse] = await Promise.all([failing, queued])
  assert.equal(failedResponse.statusCode, 500)
  assert.equal(queuedResponse.statusCode, 200)
  assert.deepEqual(started, ['fail', 'next'])
})

test('custom error handlers release slot cleanly without double-release', async () => {
  const app = Fastify()
  let active = 0
  let maximum = 0

  app.setErrorHandler((error, request, reply) => {
    reply.status(502).send({ custom: error.message })
  })

  app.get('/custom-err', {
    concurrency: { max: 1, queueLimit: 5 }
  }, async () => {
    active++
    maximum = Math.max(maximum, active)
    try {
      throw new Error('boom')
    } finally {
      active--
    }
  })

  const res1 = await app.inject('/custom-err')
  const res2 = await app.inject('/custom-err')

  assert.equal(res1.statusCode, 502)
  assert.equal(res2.statusCode, 502)
  assert.equal(maximum, 1)
})

test('keep-alive persistent socket reuse releases slots cleanly across multiple sequential requests', async t => {
  const app = Fastify()
  let active = 0
  let peak = 0

  app.get('/keep-alive', {
    concurrency: { max: 1, queueLimit: 5 }
  }, async () => {
    active++
    peak = Math.max(peak, active)
    await delay(10)
    active--
    return 'ka-ok'
  })

  await app.listen({ port: 0 })
  t.after(() => app.close())
  const port = app.server.address().port

  const agent = new http.Agent({ keepAlive: true, maxSockets: 1 })
  t.after(() => agent.destroy())

  for (let i = 0; i < 5; i++) {
    await new Promise((resolve, reject) => {
      const req = http.get({ port, path: '/keep-alive', agent }, res => {
        res.resume()
        res.on('end', () => resolve())
      })
      req.on('error', reject)
    })
  }

  assert.equal(peak, 1)
})

test('onError hooks and preSerialization error handlers release slot cleanly', async () => {
  const app = Fastify()
  let active = 0
  let peak = 0

  app.addHook('onError', (request, reply, error, done) => {
    done()
  })

  app.get('/hook-err', {
    concurrency: { max: 1, queueLimit: 5 },
    preSerialization: async () => {
      throw new Error('serialization failed')
    }
  }, async () => {
    active++
    peak = Math.max(peak, active)
    active--
    return { data: 'test' }
  })

  const res1 = await app.inject('/hook-err')
  const res2 = await app.inject('/hook-err')

  assert.equal(res1.statusCode, 500)
  assert.equal(res2.statusCode, 500)
  assert.equal(peak, 1)
})
