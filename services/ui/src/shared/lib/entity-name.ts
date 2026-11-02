export function hasAsciiControls(value:string):boolean {return [...value].some(char=>char.charCodeAt(0)<32||char.charCodeAt(0)===127)}
/** Mirrors the owner's 1–255 character name constraint; authority stays server-side. */
export function entityNameError(value:string):string{
  const name=value.trim()
  if(!name)return 'Укажите название.'
  if([...name].length>255||hasAsciiControls(name))return 'Название: от 1 до 255 символов, без управляющих знаков.'
  return ''
}
