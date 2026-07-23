import { defineConfig } from "vitest/config"

export default defineConfig({
  test: {
    include: ["test/__hidden__*.test.ts"],
    testTimeout: 60000,
    hookTimeout: 240000,
  },
})
