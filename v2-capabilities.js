(function (root) {
  const capabilities = caps => ['rest', 'flight', 'streaming', 'bind_parameters']
    .map(name => name.replace('_', ' ') + ': ' + (caps?.[name] === true ? 'yes' : caps?.[name] === false ? 'no' : 'unknown')).join(' · ');
  if (typeof module === 'object' && module.exports) module.exports = { capabilities };
  else root.V2Capabilities = { capabilities };
})(globalThis);
