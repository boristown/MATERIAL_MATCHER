import { Message, MessageBox } from 'element-ui'

type MsgArg = string | Record<string, unknown>

function ElMessage(options: MsgArg): unknown {
  return Message(typeof options === 'string' ? { message: options } : options)
}

ElMessage.success = (options: MsgArg): unknown =>
  Message(typeof options === 'string' ? { message: options, type: 'success' } : { type: 'success', ...options })
ElMessage.error = (options: MsgArg): unknown =>
  Message(typeof options === 'string' ? { message: options, type: 'error' } : { type: 'error', ...options })
ElMessage.warning = (options: MsgArg): unknown =>
  Message(typeof options === 'string' ? { message: options, type: 'warning' } : { type: 'warning', ...options })
ElMessage.info = (options: MsgArg): unknown =>
  Message(typeof options === 'string' ? { message: options, type: 'info' } : { type: 'info', ...options })

export { ElMessage }
export const ElMessageBox = MessageBox as unknown as typeof MessageBox & Record<string, any>
export default {}
