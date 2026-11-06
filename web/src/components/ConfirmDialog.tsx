import { useEffect } from 'react'

interface Props {
  title: string
  description: string
  confirmText: string
  danger?: boolean
  busy?: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function ConfirmDialog({
  title,
  description,
  confirmText,
  danger,
  busy,
  onCancel,
  onConfirm,
}: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onCancel])

  return (
    <div className="overlay" onClick={() => !busy && onCancel()}>
      <div className="confirm" onClick={(e) => e.stopPropagation()}>
        <h3>{title}</h3>
        <p>{description}</p>
        <div className="confirm-actions">
          <button className="btn btn-ghost" onClick={onCancel} disabled={busy}>
            取消
          </button>
          <button
            className={`btn ${danger ? '' : 'btn-primary'}`}
            style={danger ? { borderColor: 'rgba(255,107,138,.5)', color: '#ffc7d3' } : undefined}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? <span className="spinner" /> : null}
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}
