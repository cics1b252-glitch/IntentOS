const notice = document.getElementById('windows-alpha-notice');

if (notice && new URLSearchParams(globalThis.location.search).get('host') === 'windows-alpha') {
  notice.hidden = false;
}
