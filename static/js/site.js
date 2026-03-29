const wireTableSearch = (inputSelector, rowSelector) => {
  const searchInput = document.querySelector(inputSelector);
  const rows = document.querySelectorAll(rowSelector);

  if (!searchInput || rows.length === 0) {
    return;
  }

  searchInput.addEventListener('input', (event) => {
    const query = event.target.value.trim().toLowerCase();

    rows.forEach((row) => {
      const matches = row.textContent.toLowerCase().includes(query);
      row.hidden = !matches;
    });
  });
};

const setInlineStatus = (statusElement, ok) => {
  if (!statusElement) {
    return;
  }

  statusElement.textContent = ok ? '\u2713' : '\u2715';
  statusElement.classList.toggle('is-success', ok);
  statusElement.classList.toggle('is-error', !ok);
  window.setTimeout(() => {
    statusElement.textContent = '';
    statusElement.classList.remove('is-success', 'is-error');
  }, ok ? 1200 : 1800);
};

const formatMoney = (value) => {
  const amount = Number.parseFloat(value || 0);
  if (Number.isNaN(amount)) {
    return '-';
  }
  return amount === 0 ? '-' : `\u00a3${amount.toFixed(2)}`;
};

const updateCashRow = (row, entry, statusElement) => {
  const itemCell = row.querySelector('[data-field="entry_type"]');
  const nameCell = row.querySelector('[data-field="entry_name"]');
  const categoryCell = row.querySelector('[data-field="category_name"]');
  const moneyInCell = row.querySelector('[data-field="money_in"]');
  const moneyOutCell = row.querySelector('[data-field="money_out"]');
  const notesCell = row.querySelector('[data-field="notes"]');

  if (itemCell) itemCell.textContent = entry.entry_type;
  if (nameCell) nameCell.textContent = entry.entry_name;
  if (categoryCell) {
    categoryCell.textContent = entry.category_name || 'Unassigned';
    categoryCell.classList.toggle('muted-text', !entry.category_name);
    categoryCell.classList.toggle('pill', !!entry.category_name);
  }
  if (moneyInCell) moneyInCell.textContent = formatMoney(entry.money_in);
  if (moneyOutCell) moneyOutCell.textContent = formatMoney(entry.money_out);
  if (notesCell) notesCell.textContent = entry.notes || '-';

  setInlineStatus(statusElement, true);
};

const updateCashMeeting = (block, settlement) => {
  const totalInCell = block.querySelector('[data-meeting-total-in]');
  const totalOutCell = block.querySelector('[data-meeting-total-out]');
  const settledCell = block.querySelector('[data-meeting-settled]');
  const remainingCell = block.querySelector('[data-meeting-remaining]');
  const list = block.querySelector('[data-meeting-settlement-list]');
  const emptyNote = block.querySelector('[data-meeting-empty-settlement]');
  const form = block.querySelector('[data-cash-settle-form]');

  if (totalInCell) {
    totalInCell.textContent = Number.parseFloat(settlement.total_in || 0).toFixed(2);
  }
  if (totalOutCell) {
    totalOutCell.textContent = Number.parseFloat(settlement.total_out || 0).toFixed(2);
  }
  if (settledCell) {
    settledCell.textContent = Number.parseFloat(settlement.settled_total || 0).toFixed(2);
  }
  if (remainingCell) {
    remainingCell.textContent = Number.parseFloat(settlement.remaining_to_bank || 0).toFixed(2);
  }

  if (list) {
    if (emptyNote) {
      emptyNote.remove();
    }

    const item = document.createElement('div');
    item.className = 'cash-deposit-item';
    item.innerHTML = `
      <span class="pill">Deposit</span>
      <span>${formatMoney(settlement.net_amount)}</span>
      <span>${settlement.settlement_date}</span>
      ${settlement.bank_transaction_id ? `<span>#${settlement.bank_transaction_id}</span>` : ''}
    `;
    list.appendChild(item);
  }

  if (form) {
    const amountInput = form.querySelector('input[name="deposit_amount"]');
    const dateInput = form.querySelector('input[name="settlement_date"]');

    if (Number.parseFloat(settlement.remaining_to_bank || 0) > 0) {
      if (amountInput) {
        amountInput.value = Number.parseFloat(settlement.remaining_to_bank).toFixed(2);
      }
      if (dateInput && settlement.settlement_date) {
        dateInput.value = settlement.settlement_date;
      }
    } else {
      const note = document.createElement('span');
      note.className = 'section-note';
      note.textContent = 'Meeting cash fully settled.';
      form.replaceWith(note);
    }
  }
};

const sendJsonForm = async (form) => {
  const response = await fetch(form.action, {
    method: 'POST',
    body: new FormData(form),
    headers: {
      'X-Requested-With': 'XMLHttpRequest',
      Accept: 'application/json',
    },
  });

  let payload = {};
  try {
    payload = await response.json();
  } catch (_error) {
    payload = {};
  }

  if (!response.ok) {
    throw new Error(payload.message || 'Save failed');
  }

  return payload;
};

document.querySelectorAll('.bank-category-select[data-autosubmit="true"]').forEach((select) => {
  select.addEventListener('change', () => {
    const form = select.closest('form');
    if (!form) {
      return;
    }

    const status = form.closest('tr')?.querySelector('.bank-row-status');
    const previousValue = select.dataset.previousValue || select.defaultValue || '';

    if (status) {
      status.textContent = '\u2026';
      status.classList.remove('is-success', 'is-error');
    }

    sendJsonForm(form)
      .then(() => {
        select.dataset.previousValue = select.value;
        setInlineStatus(status, true);
      })
      .catch(() => {
        select.value = previousValue;
        setInlineStatus(status, false);
      });
  });
});

const cashEntryForms = document.querySelectorAll('[data-cash-entry-form]');
if (cashEntryForms.length > 0) {
  cashEntryForms.forEach((form) => {
    form.addEventListener('submit', (event) => {
      event.preventDefault();

      const row = form.closest('tr[data-cash-entry-row]');
      const status = form.querySelector('[data-cash-entry-status]');

      if (status) {
        status.textContent = '\u2026';
        status.classList.remove('is-success', 'is-error');
      }

      sendJsonForm(form)
        .then((payload) => {
          if (row && payload.entry) {
            updateCashRow(row, payload.entry, status);
          } else {
            setInlineStatus(status, true);
          }
        })
        .catch(() => {
          setInlineStatus(status, false);
        });
    });
  });
}

const cashDeleteForms = document.querySelectorAll('[data-cash-delete-form]');
if (cashDeleteForms.length > 0) {
  cashDeleteForms.forEach((form) => {
    form.addEventListener('submit', (event) => {
      event.preventDefault();

      const row = form.closest('tr[data-cash-entry-row]');
      const button = form.querySelector('button[type="submit"]');
      const originalText = button ? button.textContent : '';

      if (button) {
        button.disabled = true;
        button.textContent = '...';
      }

      sendJsonForm(form)
        .then(() => {
          if (row) {
            row.remove();
          }
        })
        .catch(() => {
          if (button) {
            button.textContent = originalText;
            button.disabled = false;
          }
        });
    });
  });
}

const cashSettleForms = document.querySelectorAll('[data-cash-settle-form]');
if (cashSettleForms.length > 0) {
  cashSettleForms.forEach((form) => {
    form.addEventListener('submit', (event) => {
      event.preventDefault();

      const block = form.closest('[data-meeting-key]');
      const status = form.querySelector('[data-cash-settle-status]');

      if (status) {
        status.textContent = '\u2026';
        status.classList.remove('is-success', 'is-error');
      }

      sendJsonForm(form)
        .then((payload) => {
          if (block && payload.settlement) {
            updateCashMeeting(block, payload.settlement);
          }
          setInlineStatus(status, true);
        })
        .catch(() => {
          setInlineStatus(status, false);
        });
    });
  });
}

wireTableSearch('#memberSearch', '#membersTable tr');
wireTableSearch('#bankSearch', '#bankTable tr');
wireTableSearch('#memberPageSearch', '#memberPageTable tr');

document.querySelectorAll('.bank-category-select[data-autosubmit="true"]').forEach((select) => {
  select.dataset.previousValue = select.value;
});

const reportToggle = document.querySelector('.report-toggle');
const headerTop = document.querySelector('.site-header-top');

if (reportToggle && headerTop) {
  reportToggle.addEventListener('click', () => {
    const isOpen = headerTop.classList.toggle('reports-open');
    reportToggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  });
}

document.querySelectorAll('[data-fill-input]').forEach((button) => {
  button.addEventListener('click', () => {
    const inputName = button.dataset.fillInput;
    const inputValue = button.dataset.fillValue || '';
    const input = inputName ? document.querySelector(`[name="${inputName}"]`) : null;

    if (input) {
      input.value = inputValue;
      input.focus();
    }
  });
});

document.querySelectorAll('[data-exit-app]').forEach((button) => {
  button.addEventListener('click', async () => {
    const exitUrl = button.dataset.exitUrl;
    const status = document.querySelector('[data-exit-message]');

    if (!exitUrl) {
      return;
    }

    button.disabled = true;
    button.textContent = 'Exit requested';
    button.classList.add('is-exiting');
    if (status) {
      status.textContent = 'Exit requested. Saving a final backup and stopping the app now.';
      status.classList.remove('attention-banner-ok');
      status.classList.add('attention-banner-warning');
    }

    void fetch(exitUrl, {
      method: 'POST',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
      },
      keepalive: true,
    });

    window.setTimeout(() => {
      if (status) {
        status.textContent = 'Treasurer is stopping or has stopped. You can close this tab now.';
      }
      window.close();
    }, 1500);
  });
});
