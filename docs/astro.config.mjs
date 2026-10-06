import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightLinksValidator from 'starlight-links-validator';

export default defineConfig({
  site: 'https://anthonypluth.github.io',
  base: '/Waypoint',
  trailingSlash: 'always',
  integrations: [
    starlight({
      title: 'Waypoint',
      description: 'A self-hosted travel app for a household: flights, hotels and rental cars from your email, read privately on your own server.',
      logo: { src: './src/assets/logo.svg' },
      favicon: '/favicon.svg',
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/AnthonyPluth/waypoint' }],
      editLink: { baseUrl: 'https://github.com/AnthonyPluth/waypoint/edit/main/docs/' },
      customCss: ['./src/styles/custom.css'],
      lastUpdated: true,
      plugins: [starlightLinksValidator()],
      sidebar: [
        { label: 'Start here', items: [{ autogenerate: { directory: 'start' } }] },
        { label: 'Privacy', items: [{ autogenerate: { directory: 'privacy' } }] },
        { label: 'Reference', items: [{ autogenerate: { directory: 'reference' } }] },
        { label: 'Contributing', items: [{ autogenerate: { directory: 'contributing' } }] },
      ],
    }),
  ],
});
