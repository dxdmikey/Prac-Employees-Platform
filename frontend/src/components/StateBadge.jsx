// A state shown as a badge, coloured by what kind of state it is.
//
// The *kind* comes from metadata (is_final, plus the code for the two
// outcomes), so a new state gets a sensible badge without a code change here.
function StateBadge({ code, name, isFinal }) {
  let modifier = 'badge--state-open'
  if (isFinal) {
    modifier = code === 'REJECTED' ? 'badge--state-rejected' : 'badge--state-done'
  }

  return <span className={`badge ${modifier}`}>{name ?? code}</span>
}

export default StateBadge
