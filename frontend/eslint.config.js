export default [
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'test-results/**',
      'coverage/**',
      'vitest.config.ts.timestamp-*.mjs',
    ],
  },
  {
    files: ['**/*.{js,mjs,cjs}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        console: 'readonly',
        process: 'readonly',
      },
    },
    rules: {
      'no-undef': 'error',
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
    },
  },
]
