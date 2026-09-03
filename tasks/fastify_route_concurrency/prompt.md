# Add per-route concurrency admission controls and plugin inheritance

Fastify needs an opt-in concurrency admission mechanism that prevents expensive endpoints from admitting more work than they can safely execute, while leaving every other route unchanged.

Add the public `concurrency` configuration to route options and plugin registration options:

```js
// Per-route option:
fastify.get('/expensive', {
  concurrency: {
    max: 2,
    queueLimit: 10,
    queueTimeout: 5000
  }
}, handler)

// Plugin-level default concurrency option:
fastify.register(async function (instance) {
  instance.get('/sub-1', handler1) // inherits plugin default
  instance.get('/sub-2', { concurrency: { max: 5 } }, handler2) // explicit override
}, { concurrency: { max: 2, queueLimit: 10 } })
```

### The API Specification:

- `max` is required and must be a positive integer.
- `queueLimit` is optional, defaults to `0`, and must be a non-negative integer. It is the maximum number of requests waiting in queue.
- `queueTimeout` is optional, defaults to `30000`, and must be a positive integer number of milliseconds.
- Any invalid `concurrency` value must fail registration with a `TypeError` whose Fastify error code is `FST_ERR_ROUTE_CONCURRENCY_OPTION_INVALID`.
- `request.routeOptions.concurrency` must expose the normalized three-field object for configured/inherited routes and be `undefined` for routes without the option. Add the corresponding TypeScript declarations.
- When `fastify.register` is given a `concurrency` option, all routes registered in that plugin scope inherit the plugin's concurrency defaults unless explicitly overridden on the individual route. Encapsulated child plugins inherit parent plugin concurrency unless re-configured.

### Lifecycle and Admission Rules:

1. For a configured route, no more than `max` requests may be admitted into the route lifecycle at once. Admission happens before `onRequest` hooks and body parsing.
2. A slot remains occupied throughout the entire request-response lifecycle (including streaming response bodies) until the response finishes, errors, or terminates via client disconnect. Release each slot exactly once.
3. Requests that cannot enter immediately wait in strict FIFO order, up to `queueLimit`:
   - If the queue is disabled or already full, reject the incoming request with HTTP 503 and error code `FST_ERR_ROUTE_CONCURRENCY_QUEUE_FULL`. It must not enter route hooks or the handler.
   - If a queued request waits longer than `queueTimeout`, remove it and reply with HTTP 503 and error code `FST_ERR_ROUTE_CONCURRENCY_QUEUE_TIMEOUT`. It must not enter route hooks or the handler.
   - If a queued client disconnects, remove that entry without consuming a slot. If an admitted client disconnects, release its slot so the next live queued request can run.
4. Queue waiting is separate from Fastify's existing `handlerTimeout`: the handler timer begins only after admission.
5. Each registered route owns independent admission state. Routes without `concurrency` must retain their existing behavior and fast path.

### Requirements and Validation:

- Implement the `concurrency` route and plugin option adhering strictly to the specification above.
- Ensure TypeScript type declarations in `types/` reflect `concurrency` in route options, plugin options, and `request.routeOptions`.
- Ensure public documentation in `docs/Reference/` documents the new option and error codes.
- Ensure no regressions are introduced to standard unconstrained routes.
- Verify your implementation with unit tests and type checks (`npm run test:types`).
