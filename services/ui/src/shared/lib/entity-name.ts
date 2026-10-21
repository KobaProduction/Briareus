/** Mirrors the owner's 1–255 character name constraint; authority stays server-side. */
export function entityNameError(value:string):string{
  const name=value.trim()
  if(!name)return 'Укажите название.'
  if([...name].length>255||/[\u0000-\u001f\u007f]/.test(name))return 'Название: от 1 до 255 символов, без управляющих знаков.'
  return ''
}
