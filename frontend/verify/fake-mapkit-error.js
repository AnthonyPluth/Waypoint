(() => {
  const watch = () => {
    if (window.mapkit.__state.maps.length) {
      setTimeout(() => window.mapkit.__fail("Unauthorized"), 2500);
      return;
    }
    requestAnimationFrame(watch);
  };
  requestAnimationFrame(watch);
})();
