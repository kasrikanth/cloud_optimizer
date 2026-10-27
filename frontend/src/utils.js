export const money=n=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(n);
export function validateImport(rows){
  if(!Array.isArray(rows)||!rows.length||rows.length>500)throw Error('Import an array of 1–500 resources.');
  // The API performs authoritative field and range validation.
  return rows;
}
