const trips = Object.freeze([
  {id:'coast',name:'A week by the coast',place:'Port Azure',dates:'June 12–18, 2027',status:'Upcoming',people:'Alex & Riley Example',route:'Northfield → Port Azure',flight:'Example Air · EA 204',time:'June 12 · 09:20–11:05',hotel:'Harbor House · June 12–18',car:'Example Rentals · Compact · June 12–18',code:'DEMO-A1',cost:'$1,240'},
  {id:'mountains',name:'Mountain weekend',place:'Pinecrest',dates:'September 3–6, 2027',status:'Upcoming',people:'Alex Example',route:'Northfield → Pinecrest',flight:'Fictional Airways · FA 310',time:'September 3 · 14:00–15:15',hotel:'Pine Lodge · September 3–6',car:'No rental car',code:'DEMO-B2',cost:'$680'},
  {id:'city',name:'A little city escape',place:'Bellhaven',dates:'April 8–11, 2026',status:'Past',people:'Alex & Riley Example',route:'Northfield → Bellhaven',flight:'Example Air · EA 118',time:'April 8 · 10:00–11:30',hotel:'Bellhaven Inn · April 8–11',car:'Example Rentals · Compact · April 8–11',code:'DEMO-C3',cost:'$920'}
]);
const content = document.querySelector('#content');
const card = trip => `<a class="trip" href="#trip/${trip.id}"><span class="eyebrow">${trip.dates}</span><h2>${trip.name}</h2><p>${trip.place} · ${trip.people}</p><div class="trip-bottom"><span>✈ Flight &nbsp; ▣ Stay</span><span>View itinerary →</span></div></a>`;
function render() {
  const route = location.hash.slice(1) || 'upcoming';
  document.querySelectorAll('nav a').forEach(link => {
    const active = link.hash === `#${route}` || (route.startsWith('trip/') && link.hash === '#upcoming');
    if (active) link.setAttribute('aria-current','page');
    else link.removeAttribute('aria-current');
  });
  if (route.startsWith('trip/')) {
    const trip = trips.find(item => item.id === route.slice(5));
    if (!trip) {content.innerHTML='<h1>Trip not found</h1><a href="#upcoming">Back to trips</a>';return;}
    content.innerHTML=`<a class="back" href="#${trip.status === 'Past' ? 'past' : 'upcoming'}">← All trips</a><p class="eyebrow">${trip.dates} · ${trip.status}</p><h1>${trip.name}</h1><p class="intro">${trip.people} · ${trip.place}</p><div class="summary"><span>3 fictional reservations</span><span>${trip.cost} example total</span></div><h2>Your itinerary</h2><div class="reservations"><article><span class="icon">✈</span><div><h3>${trip.route}</h3><p>${trip.flight}</p><p>${trip.time}</p><span class="badge">Confirmation ${trip.code}</span></div></article><article><span class="icon">▣</span><div><h3>${trip.hotel}</h3><p>Check-in 15:00 · Check-out 11:00</p><p>Fictional accommodation</p></div></article><article><span class="icon">◇</span><div><h3>${trip.car}</h3><p>Fictional booking · No provider connection</p></div></article></div><button disabled>Edit trip</button>`;
  } else if (route === 'map') {
    content.innerHTML='<p class="eyebrow">Your journeys at a glance</p><h1>Travel map</h1><p class="intro">An illustrative map of fictional places. Bundled SVG, with no map tiles.</p><div class="map"><img src="map.svg" alt="Illustrative fictional coastline showing Northfield, Port Azure, Pinecrest and Bellhaven connected by travel routes"></div><div class="grid">'+trips.map(card).join('')+'</div>';
  } else if (route === 'settings') {
    content.innerHTML='<p class="eyebrow">Safe to explore</p><h1>Demo settings</h1><p class="intro">This demo has no accounts or connections. All sample data is bundled and read only.</p><div class="settings">'+['Editing','File imports','Authentication','Mail connections','External integrations'].map(name=>`<article><h2>${name}</h2><span class="badge">Unavailable in static demo</span><button disabled>${name === 'Mail connections' ? 'Connect mailbox' : name === 'File imports' ? 'Import file' : name === 'Authentication' ? 'Sign in' : name === 'External integrations' ? 'Connect service' : 'Edit data'}</button></article>`).join('')+'</div>';
  } else {
    const past = route === 'past';
    content.innerHTML=`<p class="eyebrow">A place for every journey</p><h1>${past ? 'Past trips' : 'Where to next?'}</h1><p class="intro">${past ? 'A few fictional memories from the road.' : 'Flights, stays and the details that keep your trip together.'}</p><div class="summary"><span>${past ? '1 past trip' : '2 upcoming trips'}</span><span>Fictional household · 2 travelers</span></div><div class="grid">${trips.filter(trip=>(trip.status === 'Past') === past).map(card).join('')}</div><button disabled>Add trip</button>`;
  }
}
window.addEventListener('hashchange',render);
render();
