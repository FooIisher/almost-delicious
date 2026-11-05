(() => {
  const labels = {total_time: 'Total time', calories: 'Calories', protein: 'Protein'};
  const units = {total_time: 'minutes', calories: 'kcal / serving', protein: 'g / serving'};
  const symbols = {lt: '<', lte: '≤', gt: '>', gte: '≥', eq: '='};
  const container = document.getElementById('numeric-bounds');
  let conditions = [];
  function render(bounds = []) {
    conditions = bounds.map(bound => ({...bound}));
    container.replaceChildren();
    conditions.forEach(condition => {
      const row = document.createElement('div');
      row.className = 'controls';
      const label = document.createElement('label');
      label.className = 'field';
      label.textContent = labels[condition.field] + ' ';
      const operator = document.createElement('select');
      operator.setAttribute('aria-label', labels[condition.field] + ' comparison');
      Object.entries(symbols).forEach(([value, text]) => {
        const option = document.createElement('option');
        option.value = value; option.textContent = text; operator.append(option);
      });
      operator.value = condition.operator;
      operator.addEventListener('change', () => { condition.operator = operator.value; });
      const value = document.createElement('input');
      value.type = 'number'; value.min = '0'; value.step = 'any'; value.required = true;
      value.value = condition.value;
      value.setAttribute('aria-label', labels[condition.field] + ' value');
      value.addEventListener('input', () => { condition.value = value.value === '' ? null : Number(value.value); });
      label.append(operator, value, document.createTextNode(' ' + units[condition.field]));
      const notice = document.createElement('p');
      notice.className = 'field-help';
      const enabled = document.createElement('input');
      enabled.type = 'checkbox';
      enabled.checked = condition.field === 'total_time' || condition.basis === 'per_serving';
      condition.enabled = enabled.checked;
      const confirmed = document.createElement('label');
      confirmed.append(enabled, document.createTextNode(condition.field === 'total_time' ? ' Apply time filter' : ' Apply as per-serving nutrition filter'));
      enabled.addEventListener('change', () => { condition.enabled = enabled.checked; updateNotice(); });
      function updateNotice() {
        value.disabled = !condition.enabled;
        operator.disabled = !condition.enabled;
        notice.textContent = (condition.enabled ? 'Ready for Retrieval; applied to both BM25 and Vector. ' : 'Not applied. ') +
          (condition.field !== 'total_time' && condition.basis !== 'per_serving'
            ? `Original basis: ${condition.basis}. Enable only after confirming/editing a per-serving value. ` : '') +
          `Source: ${condition.evidence || 'manual'}`;
      }
      updateNotice(); row.append(label, confirmed, notice); container.append(row);
    });
    document.getElementById('numeric-bounds-help').textContent = conditions.length
      ? 'Review normalized values and comparison signs. Unchecked conditions are not applied. Missing recipe values do not satisfy an active range filter.'
      : 'Parsed numeric conditions appear here. Legacy maximum controls below still use ≤.';
  }
  function collect() {
    return conditions.filter(condition => condition.enabled).map(condition => {
      if (condition.value === null || !Number.isFinite(Number(condition.value)) || Number(condition.value) < 0) throw new Error('Numeric filters require a non-negative value.');
      return {field: condition.field, operator: condition.operator, value: Number(condition.value),
        basis: condition.field === 'total_time' ? 'not_applicable' : 'per_serving'};
    });
  }
  globalThis.RecipeBounds = {render, collect};
  render();
})();
