(() => {
  const form = document.querySelector("#answer-form");
  if (!form) return;

  const radios = form.querySelectorAll('input[name="response_type"]');
  const textFields = form.querySelector("#text-response-fields");
  const toolFields = form.querySelector("#tool-response-fields");

  const syncMode = () => {
    const selected = form.querySelector('input[name="response_type"]:checked');
    const isTool = selected && selected.value === "tool_call";
    if (textFields) textFields.hidden = isTool;
    if (toolFields) toolFields.hidden = !isTool;
  };
  radios.forEach((radio) => radio.addEventListener("change", syncMode));
  syncMode();
})();

