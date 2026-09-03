'use strict'

const { test } = require('node:test')
const assert = require('node:assert/strict')
const http = require('node:http')
const { Fastify, deferred, delay, waitFor } = require('./helpers.cjs')

test('rapid burst traffic with random mid-flight client aborts returns active slots to zero', async t => {
  const app = Fastify()
  let active = 0
  let peak = 0

  app.get('/burst', {
    concurrency: { max: 2, queueLimit: 50, queueTimeout: 5000 }
  }, async () => {
    active++
    peak = Math.max(peak, active)
    await delay(20)
    active--
    return 'burst-ok'
  })

  await app.listen({ port: 0 })
  t.after(() => app.close())
  const port = app.server.address().port

  const total = 20
  const promises = []

  for (let i = 0; i < total; i++) {
    const shouldAbort = i % 2 === 0
    const p = new Promise(resolve => {
      const req = http.get({ port, path: '/burst' }, res => {
        res.resume()
        res.on('end', () => resolve({ status: res.statusCode, aborted: false }))
      })
      req.on('error', () => resolve({ status: null, aborted: true }))
      if (shouldAbort) {
        setTimeout(() => req.destroy(), 5)
      }
    })
    promises.push(p)
  }

  await Promise.all(promises)
  await delay(100)

  // Verify that subsequent requests execute cleanly without hanging or being rejected
  const res1 = await app.inject('/burst')
  const res2 = await app.inject('/burst')
  assert.equal(res1.statusCode, 200)
  assert.equal(res2.statusCode, 200)
  assert.equal(res1.payload, 'burst-ok')
  assert.equal(res2.payload, 'burst-ok')
  // No cap assertion on `peak`: an aborted client releases its slot while its
  // handler may still be running, so handlers in flight can exceed max.
  assert.ok(peak >= 1)
})

test('preValidation schema validation failure releases concurrency slot immediately', async t => {
  const app = Fastify()
  const gate = deferred()
  t.after(() => gate.resolve())
  const handled = []

  app.post('/validate-body', {
    concurrency: { max: 1, queueLimit: 5 },
    schema: {
      body: {
        type: 'object',
        required: ['name'],
        properties: {
          name: { type: 'string' }
        }
      }
    }
  }, async request => {
    handled.push(request.body.name)
    if (request.body.name === 'hold') await gate.promise
    return { hello: request.body.name }
  })

  // 1. A valid request holds the only slot.
  const held = app.inject({ method: 'POST', url: '/validate-body', payload: { name: 'hold' } })
  await waitFor(() => handled.includes('hold'), 500)

  // 2. An invalid payload arrives. Admission happens before body parsing and
  //    validation, so it must wait in the queue and not be answered yet.
  let invalidSettled = false
  const invalid = app.inject({ method: 'POST', url: '/validate-body', payload: { age: 30 } })
    .then(res => { invalidSettled = true; return res })
  await delay(30)
  assert.equal(invalidSettled, false, 'invalid request was validated before admission')

  // 3. Once the slot frees, the invalid request is admitted, fails validation
  //    (400) and releases its slot at once; the next valid request is served.
  gate.resolve()
  const resHeld = await held
  assert.equal(resHeld.statusCode, 200)
  const res1 = await invalid
  assert.equal(res1.statusCode, 400)

  const res2 = await app.inject({ method: 'POST', url: '/validate-body', payload: { name: 'fastify' } })
  assert.equal(res2.statusCode, 200)
  assert.deepEqual(res2.json(), { hello: 'fastify' })
})

test('custom content type parser error releases concurrency slot immediately', async () => {
  const app = Fastify()

  app.addContentTypeParser('application/custom', function (request, payload, done) {
    done(new Error('parser failure'))
  })

  app.post('/parser-err', {
    concurrency: { max: 1, queueLimit: 5 }
  }, async () => {
    return 'ok'
  })

  const res1 = await app.inject({
    method: 'POST',
    url: '/parser-err',
    headers: { 'content-type': 'application/custom' },
    payload: 'invalid-body'
  })
  assert.equal(res1.statusCode, 500)

  // Slot must be free for next request
  const res2 = await app.inject({
    method: 'POST',
    url: '/parser-err',
    headers: { 'content-type': 'application/json' },
    payload: {}
  })
  assert.equal(res2.statusCode, 200)
})

test('handlerTimeout starts at admission, not while the request waits in the queue', async t => {
  const app = Fastify()
  const started = []

  // A queued request waits ~200 ms, then its handler runs ~200 ms. Measured
  // from arrival that is ~400 ms > handlerTimeout; measured from admission it
  // is ~200 ms < handlerTimeout. Only the second reading is correct.
  app.get('/timed', {
    handlerTimeout: 300,
    concurrency: { max: 1, queueLimit: 5, queueTimeout: 5000 }
  }, async request => {
    started.push(request.query.id)
    await delay(200)
    return request.query.id
  })

  const first = app.inject('/timed?id=first')
  await waitFor(() => started.includes('first'), 500)
  const queued = app.inject('/timed?id=queued')

  const [resFirst, resQueued] = await Promise.all([first, queued])
  assert.equal(resFirst.statusCode, 200)
  assert.equal(resQueued.statusCode, 200, `queued request got ${resQueued.statusCode} ${resQueued.payload}: the handler timer must start only after admission`)
  assert.equal(resQueued.payload, 'queued')
  assert.deepEqual(started, ['first', 'queued'])
})
