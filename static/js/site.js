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

const getRowCell = (row, fieldName) =>
  row?.querySelector(`[data-field="${fieldName}"]`);

const setRowInputsFromCells = (row) => {
  if (!row) {
    return;
  }
  const setInput = (fieldName) => {
    const cell = getRowCell(row, fieldName);
    const input = row.querySelector(`[data-input-field="${fieldName}"]`);
    if (cell && input) {
      input.value = cell.dataset.value ?? cell.textContent.trim();
    }
  };

  setInput('entry_type');
  setInput('entry_name');
  setInput('money_in');
  setInput('money_out');
  setInput('notes');

  const nameCell = getRowCell(row, 'entry_name');
  const memberSelect = row.querySelector('[data-input-field="member_id"]');
  if (nameCell && memberSelect) {
    memberSelect.value = nameCell.dataset.memberId || '';
  }

  const categoryCell = getRowCell(row, 'category_name');
  const categorySelect = row.querySelector('[data-input-field="ledger_category_id"]');
  if (categoryCell && categorySelect) {
    categorySelect.value = categoryCell.dataset.categoryId || '';
  }
};

const refreshCashEntryNameField = (row) => {
  if (!row) {
    return;
  }
  const entryTypeCell = getRowCell(row, 'entry_type');
  const entryTypeValue = entryTypeCell?.dataset.value?.trim().toLowerCase() || '';
  row.classList.toggle('is-member-entry', entryTypeValue === 'member');
};

const updateCashRow = (row, entry, statusElement) => {
  const itemCell = row.querySelector('[data-field="entry_type"]');
  const nameCell = row.querySelector('[data-field="entry_name"]');
  const categoryCell = row.querySelector('[data-field="category_name"]');
  const moneyInCell = row.querySelector('[data-field="money_in"]');
  const moneyOutCell = row.querySelector('[data-field="money_out"]');
  const notesCell = row.querySelector('[data-field="notes"]');

  if (itemCell) {
    itemCell.textContent = entry.entry_type;
    itemCell.dataset.value = entry.entry_type;
  }
  if (nameCell) {
    nameCell.textContent = entry.entry_name;
    nameCell.dataset.value = entry.entry_name;
    nameCell.dataset.memberId = entry.member_id || '';
  }
  if (categoryCell) {
    categoryCell.textContent = entry.category_name || 'Unassigned';
    categoryCell.classList.toggle('muted-text', !entry.category_name);
    categoryCell.classList.toggle('pill', !!entry.category_name);
    categoryCell.dataset.categoryId = entry.category_id || '';
  }
  if (moneyInCell) {
    moneyInCell.textContent = formatMoney(entry.money_in);
    moneyInCell.dataset.value = entry.money_in || 0;
  }
  if (moneyOutCell) {
    moneyOutCell.textContent = formatMoney(entry.money_out);
    moneyOutCell.dataset.value = entry.money_out || 0;
  }
  if (notesCell) {
    notesCell.textContent = entry.notes || '-';
    notesCell.dataset.value = entry.notes || '';
  }

  setRowInputsFromCells(row);
  refreshCashEntryNameField(row);
  row.classList.remove('is-editing');
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

const showBankSettlementSuccess = (form, meeting, settlement) => {
  const cell = form.closest('.meeting-cell');
  if (!cell) {
    return;
  }
  const meetingName = meeting?.meeting_name || meeting?.meeting_key || settlement?.meeting_key || '';
  const settledDate = settlement?.settlement_date || meeting?.meeting_date || '';
  cell.innerHTML = '';
  if (meetingName) {
    const label = document.createElement('span');
    label.className = 'pill';
    label.textContent = `Settled to ${meetingName}`;
    cell.appendChild(label);
  }
  if (settledDate) {
    const note = document.createElement('p');
    note.className = 'section-note';
    note.textContent = settledDate;
    cell.appendChild(note);
  }
};

const updateBankAllocationSummary = (form) => {
  const summary = form.querySelector('[data-bank-allocation-summary]');
  if (!summary) {
    return;
  }

  const transactionTotal = Number.parseFloat(form.dataset.transactionAmount || 0);
  const allocationTotal = Array.from(form.querySelectorAll('[data-bank-allocation-amount]')).reduce(
    (sum, input) => sum + (Number.parseFloat(input.value || 0) || 0),
    0,
  );

  summary.textContent = `Split total ${formatMoney(allocationTotal)} of ${formatMoney(transactionTotal)}`;
};

const scheduleBankSplitAutosave = (form, status, row, rowStatus) => {
  if (form._bankSplitSaveTimer) {
    clearTimeout(form._bankSplitSaveTimer);
  }

  form._bankSplitSaveTimer = setTimeout(() => {
    sendJsonForm(form)
      .then(() => {
        setInlineStatus(status, true);
        if (row) {
          row.classList.remove('needs-attention');
        }
        if (rowStatus) {
          rowStatus.textContent = '';
          rowStatus.classList.remove('is-needed');
        }
        updateBankMeetingControls(form);
      })
      .catch(() => {
        setInlineStatus(status, false);
      });
  }, 250);
};

const setBankAllocationMode = (form, mode, seedCategoryId = '') => {
  const single = form.querySelector('[data-bank-allocation-single]');
  const split = form.querySelector('[data-bank-allocation-split]');
  const singlePicker = form.querySelector('[data-bank-allocation-single-picker]');
  const singleAmount = form.querySelector('[data-bank-allocation-single-amount]');
  const splitInputs = form.querySelectorAll(
    '[data-bank-allocation-split] [data-bank-allocation-category], [data-bank-allocation-split] [data-bank-allocation-amount]',
  );
  const row = form.closest('tr');
  const splitActions = row?.querySelector('[data-bank-allocation-split-actions]');

  form.dataset.bankSplitMode = mode === 'split' ? 'true' : 'false';
  if (row) {
    row.classList.toggle('is-split', mode === 'split');
  }

  if (single) {
    single.hidden = mode === 'split';
  }
  if (split) {
    split.hidden = mode !== 'split';
  }
  if (splitActions) {
    splitActions.hidden = mode !== 'split';
  }
  if (singlePicker) {
    if (mode === 'split') {
      singlePicker.disabled = true;
      singlePicker.value = '__split__';
    } else {
      singlePicker.disabled = false;
      if (seedCategoryId) {
        singlePicker.value = seedCategoryId;
      } else if (singlePicker.value === '__split__') {
        singlePicker.value = '';
      }
    }
  }
  if (singleAmount) {
    singleAmount.value = form.dataset.transactionAmount || '0';
  }

  splitInputs.forEach((field) => {
    field.disabled = mode !== 'split';
  });

  if (mode === 'split') {
    const rows = form.querySelector('[data-bank-allocation-rows]');
    if (rows && rows.querySelectorAll('[data-bank-allocation-row]').length === 0) {
      addBankAllocationRow(form);
      addBankAllocationRow(form);
    }
    updateBankAllocationSummary(form);
  }

  updateBankMeetingControls(form);
};

const updateBankMeetingControls = (form) => {
  const row = form.closest('tr');
  if (!row) {
    return;
  }

  const controls = row.querySelector('[data-bank-meeting-controls]');
  const hint = row.querySelector('[data-bank-meeting-hint]');
  const splitMode = form.dataset.bankSplitMode === 'true';
  const hasCashAllocation = splitMode
    ? Array.from(form.querySelectorAll('[data-bank-allocation-category]')).some(
        (select) => select.selectedOptions?.[0]?.dataset.categoryCode === 'CASH',
      )
    : form.querySelector('[data-bank-allocation-single-picker]')?.selectedOptions?.[0]?.dataset.categoryCode === 'CASH';

  if (controls) {
    controls.hidden = !hasCashAllocation;
  }
  if (hint) {
    hint.hidden = hasCashAllocation;
  }
};

const addBankAllocationRow = (form, preset = {}) => {
  const template = form.querySelector('[data-bank-allocation-template]');
  const rows = form.querySelector('[data-bank-allocation-rows]');
  if (!template || !rows) {
    return null;
  }

  const fragment = template.content.cloneNode(true);
  const row = fragment.querySelector('[data-bank-allocation-row]');
  if (!row) {
    return null;
  }

  const select = row.querySelector('[data-bank-allocation-category]');
  const amount = row.querySelector('[data-bank-allocation-amount]');
  if (select && preset.ledger_category_id) {
    select.value = String(preset.ledger_category_id);
  }
  if (amount) {
    if (preset.amount !== undefined && preset.amount !== null && preset.amount !== '') {
      amount.value = Number.parseFloat(preset.amount).toFixed(2);
    } else {
      amount.value = '';
    }
  }

  rows.appendChild(row);
  wireBankAllocationRow(form, row);
  return row;
};

const wireBankAllocationRow = (form, row) => {
  const select = row.querySelector('[data-bank-allocation-category]');
  const amount = row.querySelector('[data-bank-allocation-amount]');

  if (select) {
    select.addEventListener('change', () => {
      updateBankMeetingControls(form);
      updateBankAllocationSummary(form);
    });
  }

  if (amount) {
    amount.addEventListener('input', () => {
      updateBankAllocationSummary(form);
    });
  }
};

const wireBankAllocationForm = (form) => {
  const singlePicker = form.querySelector('[data-bank-allocation-single-picker]');
  const status = form.querySelector('[data-bank-allocation-status]');
  const row = form.closest('tr');
  const splitAdd = row?.querySelector('[data-bank-split-add]');
  const splitCancel = row?.querySelector('[data-bank-split-cancel]');
  const splitSave = row?.querySelector('[data-bank-split-save]');
  const rowStatus = form.closest('tr')?.querySelector('.bank-row-status');
  const splitRows = form.querySelector('[data-bank-allocation-rows]');

  form.dataset.transactionAmount = form.dataset.transactionAmount || '0';

  form.querySelectorAll('[data-bank-allocation-row]').forEach((row) => {
    wireBankAllocationRow(form, row);
  });

  if (singlePicker) {
    let previousValue = singlePicker.value;
    singlePicker.addEventListener('focus', () => {
      previousValue = singlePicker.value;
    });
    singlePicker.addEventListener('change', () => {
      const selectedValue = singlePicker.value;
      if (selectedValue === '__split__') {
        form.dataset.bankPreviousCategory = previousValue && previousValue !== '__split__' ? previousValue : '';
        setBankAllocationMode(form, 'split', previousValue && previousValue !== '__split__' ? previousValue : '');
        return;
      }
      const hiddenAmount = form.querySelector('[data-bank-allocation-single-amount]');
      if (hiddenAmount) {
        hiddenAmount.value = form.dataset.transactionAmount || '0';
      }
      sendJsonForm(form)
        .then(() => {
          if (row) {
            row.classList.remove('needs-attention');
          }
          if (rowStatus) {
            rowStatus.textContent = '';
            rowStatus.classList.remove('is-needed');
          }
          updateBankMeetingControls(form);
        })
        .catch(() => {
          singlePicker.value = previousValue;
        });
    });
  }

  if (splitCancel) {
    splitCancel.addEventListener('click', () => {
      const previousCategory = form.dataset.bankPreviousCategory || '';
      if (splitRows) {
        splitRows.innerHTML = '';
      }
      setBankAllocationMode(form, 'single', previousCategory);
      updateBankAllocationSummary(form);
    });
  }

  if (splitAdd) {
    splitAdd.addEventListener('click', () => {
      if (form.dataset.bankSplitMode !== 'true') {
        return;
      }
      const newRow = addBankAllocationRow(form);
      if (newRow) {
        const focusTarget = newRow.querySelector('[data-bank-allocation-category]');
        if (focusTarget) {
          focusTarget.focus();
        }
      }
    });
  }

  if (splitSave) {
    splitSave.addEventListener('click', () => {
      if (form.dataset.bankSplitMode === 'true') {
        form.requestSubmit();
      }
    });
  }

  form.addEventListener('submit', (event) => {
    if (form.dataset.bankSplitMode !== 'true') {
      return;
    }
    event.preventDefault();
    if (status) {
      status.textContent = '…';
      status.classList.remove('is-success', 'is-error');
    }
    sendJsonForm(form)
      .then(() => {
        setInlineStatus(status, true);
        if (row) {
          row.classList.remove('needs-attention');
        }
        if (rowStatus) {
          rowStatus.textContent = '';
          rowStatus.classList.remove('is-needed');
        }
        updateBankMeetingControls(form);
      })
      .catch(() => {
        setInlineStatus(status, false);
      });
  });

  setBankAllocationMode(form, form.dataset.bankSplitMode === 'true' ? 'split' : 'single');
  updateBankAllocationSummary(form);
};

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

const attachCashRowControls = () => {
  document.querySelectorAll('[data-cash-entry-row]').forEach((row) => {
    refreshCashEntryNameField(row);
    const entryTypeInput = row.querySelector('[data-input-field="entry_type"]');
    if (entryTypeInput) {
      entryTypeInput.addEventListener('input', () => {
        const entryTypeCell = getRowCell(row, 'entry_type');
        if (entryTypeCell) {
          entryTypeCell.dataset.value = entryTypeInput.value;
        }
        refreshCashEntryNameField(row);
      });
    }
  });

  document.querySelectorAll('[data-cash-entry-edit-toggle]').forEach((button) => {
    button.addEventListener('click', () => {
      const row = button.closest('tr[data-cash-entry-row]');
      if (!row) {
        return;
      }
      setRowInputsFromCells(row);
      refreshCashEntryNameField(row);
      row.classList.add('is-editing');
      const firstInput = row.querySelector('.cash-field-input');
      if (firstInput) {
        firstInput.focus();
      }
    });
  });

  document.querySelectorAll('[data-cash-entry-edit-cancel]').forEach((button) => {
    button.addEventListener('click', () => {
      const row = button.closest('tr[data-cash-entry-row]');
      if (!row) {
        return;
      }
      row.classList.remove('is-editing');
      setRowInputsFromCells(row);
      refreshCashEntryNameField(row);
    });
  });
};

attachCashRowControls();

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

const bankSettlementForms = document.querySelectorAll('[data-bank-settlement-form]');
if (bankSettlementForms.length > 0) {
  bankSettlementForms.forEach((form) => {
    form.addEventListener('submit', (event) => {
      event.preventDefault();

      const status = form.querySelector('[data-bank-settlement-status]');
      if (status) {
        status.textContent = '\u2026';
        status.classList.remove('is-success', 'is-error');
      }

      sendJsonForm(form)
        .then((payload) => {
          showBankSettlementSuccess(form, payload.meeting, payload.settlement);
          setInlineStatus(status, true);
        })
        .catch(() => {
          setInlineStatus(status, false);
        });
    });
  });
}

const bankSettlementUnlinkForms = document.querySelectorAll('[data-bank-settlement-unlink-form]');
if (bankSettlementUnlinkForms.length > 0) {
  bankSettlementUnlinkForms.forEach((form) => {
    form.addEventListener('submit', (event) => {
      event.preventDefault();

      const status = form.closest('.meeting-cell')?.querySelector('[data-bank-settlement-status]');
      if (status) {
        status.textContent = '\u2026';
        status.classList.remove('is-success', 'is-error');
      }

      sendJsonForm(form)
        .then(() => {
          window.location.reload();
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

document.querySelectorAll('[data-bank-allocation-form]').forEach((form) => {
  wireBankAllocationForm(form);
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

let appExitRequested = false;

document.querySelectorAll('[data-exit-app]').forEach((button) => {
  button.addEventListener('click', async () => {
    const exitUrl = button.dataset.exitUrl || '/app/exit';
    const status = document.querySelector('[data-exit-message]');
    const exitButtons = document.querySelectorAll('[data-exit-app]');

    if (!exitUrl) {
      return;
    }

    exitButtons.forEach((exitButton) => {
      exitButton.disabled = true;
      exitButton.textContent = 'Exit requested';
      exitButton.classList.add('is-exiting');
    });
    if (status) {
      status.textContent = 'Exit requested. Saving a final backup and stopping the app now.';
      status.classList.remove('attention-banner-ok');
      status.classList.add('attention-banner-warning');
    }

    if (!appExitRequested) {
      appExitRequested = true;
      const payload = new Blob([], { type: 'text/plain' });
      if (!(navigator.sendBeacon && navigator.sendBeacon(exitUrl, payload))) {
        void fetch(exitUrl, {
          method: 'POST',
          headers: {
            'X-Requested-With': 'XMLHttpRequest',
          },
          keepalive: true,
        });
      }
    }

    window.setTimeout(() => {
      if (status) {
        status.textContent = 'Treasurer is stopping or has stopped. You can close this tab now.';
      }
      window.close();
    }, 1500);
  });
});
