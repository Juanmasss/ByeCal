function toastOk(msg, ms=3500){
  Toastify({
    text: msg,
    duration: ms,
    close: true,
    gravity: "top",       // puede ser "top" o "bottom"
    position: "center",   // 👈 centrado
    style: { background: "#28a745", borderRadius: "10px" } // verde éxito
  }).showToast();
}

function toastErr(msg, ms=4000){
  Toastify({
    text: msg,
    duration: ms,
    close: true,
    gravity: "top",
    position: "center",
    style: { background: "#c62828", borderRadius: "10px" } // rojo oscuro para error
  }).showToast();
}