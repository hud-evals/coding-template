'use strict'

const { test } = require('node:test')
const assert = require('node:assert/strict')
const http = require('node:http')
const { Readable } = require('node:stream')
const { Fastify, deferred, delay, waitFor } = require('./helpers.cjs')

test('readable stream response body holds concurrency slot until stream completes', async t => {
  const app = Fastify()
  let active = 0
  let peak = 0

  app.get('/stream', {
    concurrency: { max: 1, queueLimit: 5 }
  }, async (request, reply) => {
    active++
    peak = Math.max(peak, active)

    const stream = new Readable({
      read () {}
    })

    setTimeout(() => {
      stream.push('chunk1')
    }, 10)

    setTimeout(() => {
      stream.push('chunk2')
    }, 25)

    setTimeout(() => {
      stream.push(null)
      active--
    }, 45)

    return reply.send(stream)
  })

  await app.listen({ port: 0 })
  t.after(() => app.close())
  const port = app.server.address().port

  function makeReq () {
    return new Promise(resolve => {
      const req = http.get({ port, path: '/stream' }, res => {
        let body = ''
        res.on('data', chunk => { body += chunk })
        res.on('end', () => resolve({ statusCode: res.statusCode, body }))
      })
      req.on('error', err => resolve({ statusCode: 500, error: err }))
    })
  }

  const [res1, res2] = await Promise.all([makeReq(), makeReq()])

  assert.equal(res1.statusCode, 200)
  assert.equal(res2.statusCode, 200)
  assert.equal(res1.body, 'chunk1chunk2')
  assert.equal(res2.body, 'chunk1chunk2')
  assert.equal(peak, 1, `Slot was released prematurely during stream piping, peak active was ${peak}`)
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

test('reply.hijack streaming releases slot on socket close', async t => {
  const app = Fastify()
  const started = []

  app.get('/hijack', {
    concurrency: { max: 1, queueLimit: 2, queueTimeout: 2000 }
  }, (request, reply) => {
    started.push('hijack')
    reply.hijack()
    reply.raw.writeHead(200, { 'Content-Type': 'text/plain' })
    reply.raw.write('hello ')
    setTimeout(() => {
      reply.raw.end('world')
    }, 40)
  })

  app.get('/after-hijack', {
    concurrency: { max: 1 }
  }, async () => {
    started.push('after-hijack')
    return 'ok'
  })

  await app.listen({ port: 0 })
  t.after(() => app.close())
  const port = app.server.address().port

  const hijackReq = new Promise(resolve => {
    const req = http.get({ port, path: '/hijack' }, res => {
      let data = ''
      res.on('data', chunk => { data += chunk })
      res.on('end', () => resolve(data))
    })
    req.on('error', () => resolve(''))
  })

  await waitFor(() => started.includes('hijack'), 500)
  const afterReq = new Promise(resolve => {
    const req = http.get({ port, path: '/after-hijack' }, res => {
      res.resume()
      res.on('end', resolve)
    })
    req.on('error', () => resolve(''))
  })

  const [hijackBody] = await Promise.all([hijackReq, afterReq])
  assert.equal(hijackBody, 'hello world')
  assert.deepEqual(started, ['hijack', 'after-hijack'])
})

test('aborted client disconnect during active response streaming releases slot for next queued request', async t => {
  const app = Fastify()
  const started = []

  app.get('/stream-abort', {
    concurrency: { max: 1, queueLimit: 5, queueTimeout: 2000 }
  }, async (request, reply) => {
    started.push(request.query.id)
    if (request.query.id === '1') {
      const stream = new Readable({ read () {} })
      stream.push('chunk')
      return reply.send(stream)
    }
    return 'second-ok'
  })

  await app.listen({ port: 0 })
  t.after(() => app.close())
  const port = app.server.address().port

  // The first client receives the head of a stream that never ends, then
  // disconnects. `req.destroy()` emits 'close' (not necessarily 'error') on the
  // client request, so the promise settles on 'close'.
  let rawClient
  const firstReq = new Promise(resolve => {
    rawClient = http.get({ port, path: '/stream-abort?id=1' }, res => {
      res.on('data', () => {})
      res.on('error', () => {})
    })
    rawClient.on('error', () => {})
    rawClient.on('close', () => resolve())
  })

  await waitFor(() => started.includes('1'), 500)

  const secondReq = new Promise(resolve => {
    const req = http.get({ port, path: '/stream-abort?id=2' }, res => {
      let body = ''
      res.on('data', c => { body += c })
      res.on('end', () => resolve({ statusCode: res.statusCode, body }))
    })
    req.on('error', err => resolve({ statusCode: 0, body: '', error: err.code }))
  })

  await delay(20)
  assert.deepEqual(started, ['1'], 'second request must wait while the stream holds the only slot')

  // Abort the first client connection
  rawClient.destroy()
  await firstReq

  // The slot must be released by the disconnect and the queued request admitted
  // well before its 2000 ms queueTimeout.
  await waitFor(() => started.includes('2'), 1000).catch(() => {
    assert.fail('slot was not released after the streaming client disconnected: queued request never admitted')
  })
  assert.deepEqual(started, ['1', '2'])
  const second = await secondReq
  assert.equal(second.statusCode, 200)
  assert.equal(second.body, 'second-ok')
})
