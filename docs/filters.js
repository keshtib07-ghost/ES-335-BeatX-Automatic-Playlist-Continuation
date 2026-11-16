'use strict';

const filterGroups = {
  Era: [['80s', '80s'], ['90s', '90s'], ['00s', '00s'], ['10s', '10s']],
  Mood: [['happy', 'Happy'], ['chill', 'Chill'], ['sad', 'Sad'], ['upbeat', 'Upbeat'], ['angry', 'Angry']],
  Theme: [['romantic', 'Romantic / love'], ['heartbreak', 'Heartbreak / breakup']],
  Weather: [['rainy', 'Rainy'], ['summer', 'Summer'], ['winter', 'Winter']],
  Party: [['party', 'Any party'], ['dance', 'Dance'], ['rave', 'Rave'], ['dj_club', 'DJ / club']],
  Activity: [['study_focus', 'Study / focus'], ['drive', 'Drive / car'], ['relax', 'Relax'], ['gym', 'Workout'], ['sleep', 'Sleep']],
};
const filterLabels = Object.fromEntries(Object.values(filterGroups).flat());

function setupFilters() {
  const section = document.getElementById('profile-filters');
  const content = document.getElementById('filter-content');
  const active = document.getElementById('active-filters');
  const drawer = document.getElementById('filter-drawer');
  const open = document.getElementById('open-filters');
  const create = (tag, text) => {
    const item = document.createElement(tag);
    if (text) item.textContent = text;
    return item;
  };
  const selections = [];
  const group = (title) => {
    const option = create('details');
    option.append(create('summary', title));
    content.append(option);
    return option;
  };
  const refresh = () => {
    const chips = selections.flatMap(({control, label, read, clear}) => {
      const value = read();
      if (value === null || value === '') return [];
      const chip = create('button', `${label}${typeof value === 'boolean' ? '' : ` · ${value}`} ×`);
      chip.className = 'chip';
      chip.type = 'button';
      chip.setAttribute('aria-label', `Remove ${label} filter`);
      chip.addEventListener('click', () => {
        clear(control);
        refresh();
      });
      return [chip];
    });
    if (chips.length) {
      const clear = create('button', 'Clear all');
      clear.type = 'button';
      clear.className = 'chip';
      clear.addEventListener('click', () => {
        for (const item of selections) item.clear(item.control);
        refresh();
      });
      chips.push(clear);
    }
    active.replaceChildren(...chips);
    open.textContent = chips.length ? `Filters (${chips.length - 1})` : 'Filters';
  };
  for (const [category, labels] of Object.entries(filterGroups)) {
    const options = group(category);
    const choices = create('div');
    choices.className = 'filter-checks';
    for (const [key, name] of labels) {
      const label = create('label');
      const control = create('input');
      control.type = 'checkbox';
      control.value = key;
      label.append(control, document.createTextNode(name));
      choices.append(label);
      selections.push({control, label: name, category, key, read: () => control.checked || null,
        clear: () => { control.checked = false; }});
    }
    options.append(choices);
  }
  const tempo = group('Tempo');
  for (const [key, label] of [['min_bpm', 'Min BPM'], ['max_bpm', 'Max BPM']]) {
    const entry = create('label', label);
    const control = create('input');
    control.type = 'number';
    control.min = 30;
    control.max = 300;
    control.placeholder = 'Any';
    entry.append(control);
    tempo.append(entry);
    selections.push({control, label, category: 'Tempo', key,
      read: () => control.value === '' ? null : Number(control.value),
      clear: () => { control.value = ''; }});
  }
  content.addEventListener('change', refresh);
  open.addEventListener('click', () => {
    drawer.append(content);
    drawer.showModal();
  });
  document.getElementById('close-filters').addEventListener('click', () => drawer.close());
  drawer.addEventListener('close', () => {
    document.getElementById('desktop-filters').append(content);
    open.focus();
  });
  return {
    show: (visible) => { section.hidden = !visible; },
    restore: (values) => {
      for (const {control, category, key} of selections) {
        if (category === 'Tempo') control.value = values[key] ?? '';
        else control.checked = (values[category === 'Era' ? 'eras' : 'tags'] || []).includes(key);
      }
      refresh();
    },
    read: () => {
      const options = {tags: [], eras: []};
      for (const {category, key, read} of selections) {
        const value = read();
        if (category === 'Tempo') options[key] = value;
        else if (value) options[category === 'Era' ? 'eras' : 'tags'].push(key);
      }
      return options;
    },
  };
}
