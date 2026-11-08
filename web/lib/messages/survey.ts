// Cuestionario de riesgo (RASurvey de data/surveys.json): secciones, preguntas y respuestas.
// "español": ["English", "Français"]. Si cambia el texto en surveys.json, hay que cambiarlo aquí.
const INTRO = "A continuación se presentarán una serie de preguntas, las cuales le pedimos responda honestamente. A partir de esta información nos permitirá ayudarle a identificar el nivel de riesgo que pueda representar hacia usted";
const INTRO_EN = "Below you will find a series of questions, which we ask you to answer honestly. This information will help us identify the level of risk that may be posed to you by";
const INTRO_FR = "Vous trouverez ci-dessous une série de questions auxquelles nous vous demandons de répondre honnêtement. Ces informations nous permettront de vous aider à identifier le niveau de risque que peuvent représenter pour vous";

export const SURVEY: Record<string, [string, string]> = {
  // Secciones
  "Familia": ["Family", "Famille"],
  "Educación": ["Education", "Éducation"],
  "Profesional": ["Professional", "Professionnel"],
  "Social": ["Social", "Social"],
  "Personal": ["Personal", "Personnel"],
  [`${INTRO} la reputación de sus familiares, en factores ascendencia y descendencia.`]: [
    `${INTRO_EN} the reputation of your relatives, both ancestors and descendants.`,
    `${INTRO_FR} la réputation de vos proches, ascendants comme descendants.`],
  [`${INTRO} aquellos factores relacionados con su preparación y vida académica, la reputación de las instituciones en las que ha estudiado, acreditaciones con las que cuenta, conducta o participación en determinados grupos de interés.`]: [
    `${INTRO_EN} factors related to your training and academic life, the reputation of the institutions where you have studied, the credentials you hold, and your conduct or participation in certain interest groups.`,
    `${INTRO_FR} les facteurs liés à votre formation et à votre parcours scolaire, la réputation des établissements où vous avez étudié, vos diplômes, votre conduite ou votre participation à certains groupes d'intérêt.`],
  [`${INTRO} la reputación de las empresas en las que ha laborado, incluyendo la actual, así como las decisiones que haya tomado o responsabilidades que haya tenido y que puedan ser suceptibles a la exposición de su reputación personal.`]: [
    `${INTRO_EN} the reputation of the companies where you have worked, including your current one, as well as decisions you have made or responsibilities you have held that could expose your personal reputation.`,
    `${INTRO_FR} la réputation des entreprises où vous avez travaillé, y compris l'actuelle, ainsi que les décisions prises ou les responsabilités exercées susceptibles d'exposer votre réputation personnelle.`],
  [`${INTRO} la forma en la que estableció y ha mantenido sus  relaciones sociales durante toda su vida asimilados a amigos, conocidos, grupos e instituciones en donde ha colaborado.`]: [
    `${INTRO_EN} the way you have built and maintained your social relationships throughout your life with friends, acquaintances, groups and institutions you have worked with.`,
    `${INTRO_FR} la manière dont vous avez établi et entretenu vos relations sociales tout au long de votre vie avec amis, connaissances, groupes et institutions avec lesquels vous avez collaboré.`],
  [`${INTRO}, sus gustos personales, antecedentes, patrimonio, así como su comportamiento en general.`]: [
    `${INTRO_EN} your personal tastes, background, assets and general behavior.`,
    `${INTRO_FR} vos goûts personnels, vos antécédents, votre patrimoine ainsi que votre comportement en général.`],

  // Respuestas
  "Mala": ["Bad", "Mauvaise"],
  "Regular / Lo desconozco": ["Fair / I don't know", "Moyenne / Je ne sais pas"],
  "Buena": ["Good", "Bonne"],
  "Regular": ["Fair", "Moyenne"],
  "Sí": ["Yes", "Oui"],
  "Lo desconozco": ["I don't know", "Je ne sais pas"],
  "No": ["No", "Non"],
  "No aplica": ["Not applicable", "Sans objet"],
  "No he tenido otros matrimonios": ["I have not had other marriages", "Je n'ai pas eu d'autres mariages"],
  "Básica": ["Basic", "Primaire / collège"],
  "Media superior": ["High school", "Lycée"],
  "Licenciatura": ["Bachelor's degree", "Licence"],
  "Maestría": ["Master's degree", "Master"],
  "Doctorado": ["Doctorate", "Doctorat"],
  "Cursos y especializaciones": ["Courses and specializations", "Cours et spécialisations"],
  "Postgrado": ["Postgraduate", "Troisième cycle"],
  "No recuerdo": ["I don't remember", "Je ne me souviens pas"],
  "Entre 6 y 7.9": ["Between 6 and 7.9", "Entre 6 et 7,9"],
  "Entre 8 y 8.9": ["Between 8 and 8.9", "Entre 8 et 8,9"],
  "Entre 9 y 10": ["Between 9 and 10", "Entre 9 et 10"],
  "Excesiva": ["Excessive", "Excessive"],
  "Justa": ["Fair", "Juste"],
  "Suficiente": ["Sufficient", "Suffisante"],
  "Insuficiente / No trabajo actualmente": ["Insufficient / I am not currently working", "Insuffisante / Je ne travaille pas actuellement"],
  "Sí, pero no comprobables": ["Yes, but not verifiable", "Oui, mais non justifiables"],
  "Sí, comprobables": ["Yes, verifiable", "Oui, justifiables"],
  "Más del 60%": ["More than 60%", "Plus de 60 %"],
  "Entre el 30% y el 59%": ["Between 30% and 59%", "Entre 30 % et 59 %"],
  "Menos del 30%": ["Less than 30%", "Moins de 30 %"],
  "La mayor parte": ["Most of it", "La majeure partie"],
  "No, evado impuestos": ["No, I evade taxes", "Non, je fraude le fisc"],
  "Lo realiza un tercero": ["A third party handles it", "Un tiers s'en charge"],
  "Proyectos fracasados": ["Failed projects", "Projets ratés"],
  "Equilibrado": ["Balanced", "Équilibré"],
  "Proyectos exitosos": ["Successful projects", "Projets réussis"],
  "Sí, de forma directa": ["Yes, directly", "Oui, directement"],
  "Sí, de forma indirecta": ["Yes, indirectly", "Oui, indirectement"],
  "Fui beneficiado": ["I was favored", "J'ai été favorisé"],
  "Por mérito propio": ["On my own merit", "Par mon propre mérite"],
  "Nunca o casi nunca": ["Never or almost never", "Jamais ou presque jamais"],
  "La mayor parte de mi vida": ["Most of my life", "La majeure partie de ma vie"],
  "Siempre o casi siempre": ["Always or almost always", "Toujours ou presque toujours"],
  "Estoy afiliado a uno": ["I am a member of one", "Je suis membre d'un parti"],
  "No están a mi nombre": ["They are not in my name", "Elles ne sont pas à mon nom"],
  "Responda desde un punto de vista objetivo": ["Answer from an objective point of view", "Répondez d'un point de vue objectif"],

  // Preguntas: Familia
  "1. En general, ¿cómo calificaría la reputación de sus padres o tutores?": ["1. Overall, how would you rate the reputation of your parents or guardians?", "1. Dans l'ensemble, comment évalueriez-vous la réputation de vos parents ou tuteurs ?"],
  "2. En general, ¿cómo calificaría la reputación de sus hermanos, primos, tíos y sobrinos en primera línea?": ["2. Overall, how would you rate the reputation of your siblings, first cousins, uncles, aunts, nieces and nephews?", "2. Dans l'ensemble, comment évalueriez-vous la réputation de vos frères et sœurs, cousins, oncles, tantes, neveux et nièces au premier degré ?"],
  "3. ¿Alguno de sus padres o abuelos cometió algún acto ilícito por el cual no fue juzgado?": ["3. Did any of your parents or grandparents commit an unlawful act for which they were not tried?", "3. L'un de vos parents ou grands-parents a-t-il commis un acte illicite pour lequel il n'a pas été jugé ?"],
  "4. ¿Alguno de sus hermanos, primos, tíos o sobrinos en primera línea cometió algún acto ilícito por el cual no fue juzgado?": ["4. Did any of your siblings, first cousins, uncles, aunts, nieces or nephews commit an unlawful act for which they were not tried?", "4. L'un de vos frères et sœurs, cousins, oncles, tantes, neveux ou nièces au premier degré a-t-il commis un acte illicite pour lequel il n'a pas été jugé ?"],
  "5. ¿Algún familiar en primera línea cometió algún/nos acto ilícitos y no fue juzgado?": ["5. Did any close relative commit one or more unlawful acts and was not tried?", "5. Un proche parent a-t-il commis un ou plusieurs actes illicites sans être jugé ?"],
  "6. En general, ¿cómo calificaría la reputación de sus hijos y cónyuge?": ["6. Overall, how would you rate the reputation of your children and spouse?", "6. Dans l'ensemble, comment évalueriez-vous la réputation de vos enfants et de votre conjoint ?"],
  "7. Si ha tenido otros matrimonios, ¿cómo calificaría la reputación de sus exparejas?": ["7. If you have had other marriages, how would you rate the reputation of your former partners?", "7. Si vous avez eu d'autres mariages, comment évalueriez-vous la réputation de vos ex-conjoints ?"],
  "8. En general, ¿cómo calificaría la reputación de sus yernos, nueras, primos políticos y/o suegros?": ["8. Overall, how would you rate the reputation of your sons- and daughters-in-law, cousins by marriage and/or parents-in-law?", "8. Dans l'ensemble, comment évalueriez-vous la réputation de vos gendres, belles-filles, cousins par alliance et/ou beaux-parents ?"],
  "9. ¿Alguno de sus hijos o cónyuge cometió algún acto ilícito por el cual no fue juzgado?": ["9. Did any of your children or your spouse commit an unlawful act for which they were not tried?", "9. L'un de vos enfants ou votre conjoint a-t-il commis un acte illicite pour lequel il n'a pas été jugé ?"],
  "10. ¿Alguno de sus familiares políticos cometió algún acto ilícito por el cual no fue juzgado?": ["10. Did any of your in-laws commit an unlawful act for which they were not tried?", "10. L'un de vos parents par alliance a-t-il commis un acte illicite pour lequel il n'a pas été jugé ?"],
  "11. ¿Tiene hijos que no ha reconocido?": ["11. Do you have children you have not acknowledged?", "11. Avez-vous des enfants que vous n'avez pas reconnus ?"],
  "12. ¿Tiene hijo/s fuera de su matrimonio actual?": ["12. Do you have any children outside your current marriage?", "12. Avez-vous un ou des enfants hors de votre mariage actuel ?"],

  // Educación
  "13. En general, ¿cómo calificaría la reputación de las instituciones educativas a las que asistió o asiste?": ["13. Overall, how would you rate the reputation of the educational institutions you attended or attend?", "13. Dans l'ensemble, comment évalueriez-vous la réputation des établissements d'enseignement que vous avez fréquentés ou fréquentez ?"],
  "14. Último grado de estudios": ["14. Highest level of education", "14. Niveau d'études le plus élevé"],
  "15. ¿Cuenta actualmente con estudios además de la universidad?": ["15. Do you currently have studies beyond university?", "15. Avez-vous actuellement des études au-delà de l'université ?"],
  "16. ¿Alguna vez realizo un acto ilícito en la escuela para verse beneficiado de alguna manera?": ["16. Did you ever commit an unlawful act at school to benefit in some way?", "16. Avez-vous déjà commis un acte illicite à l'école pour en tirer un avantage ?"],
  "17. ¿Cuál fue su promedio general en su trayectoria educativa?": ["17. What was your overall grade average throughout your education (out of 10)?", "17. Quelle a été votre moyenne générale au cours de votre parcours scolaire (sur 10) ?"],
  "18. ¿Tuvo problemas de conducta en su trayectoria educativa?": ["18. Did you have behavioral problems during your education?", "18. Avez-vous eu des problèmes de comportement au cours de votre parcours scolaire ?"],
  "19. ¿Cometió o estuvo involucrado en actos no éticos en su trayectoria educativa?": ["19. Did you commit or were you involved in unethical acts during your education?", "19. Avez-vous commis des actes contraires à l'éthique ou y avez-vous été mêlé au cours de votre parcours scolaire ?"],

  // Profesional
  "20. ¿Cómo considera que fue la remuneración percibida en puestos anteriores en comparación al desempeño realizado en sus funciones?": ["20. How do you consider the pay you received in previous positions compared with your performance in them?", "20. Comment jugez-vous la rémunération perçue dans vos postes précédents par rapport à votre performance ?"],
  "21. ¿Cómo considera que es la remuneración que percibe actualmente en comparación al desempeño de sus funciones?": ["21. How do you consider your current pay compared with your performance in your role?", "21. Comment jugez-vous votre rémunération actuelle par rapport à votre performance dans vos fonctions ?"],
  "22. ¿Tiene ingresos adicionales a su fuente primaria de ingresos?": ["22. Do you have income in addition to your primary source of income?", "22. Avez-vous des revenus en plus de votre source principale de revenus ?"],
  "23. ¿Qué porcentaje de sus ingresos representan sus deudas actuales?": ["23. What percentage of your income do your current debts represent?", "23. Quel pourcentage de vos revenus représentent vos dettes actuelles ?"],
  "24. ¿Tiene forma de comprobar que su patrimonio fue adquirido de forma lícita?": ["24. Can you prove that your assets were acquired lawfully?", "24. Pouvez-vous prouver que votre patrimoine a été acquis de manière licite ?"],
  "25. ¿Paga los impuestos que le corresponden de acuerdo con sus ingresos?": ["25. Do you pay the taxes that correspond to your income?", "25. Payez-vous les impôts correspondant à vos revenus ?"],
  "26. ¿Cuenta con alguna propiedad u objeto que haya sido obtenido de manera ilícita?": ["26. Do you own any property or item that was obtained unlawfully?", "26. Possédez-vous un bien ou un objet obtenu de manière illicite ?"],
  "27. En general, ¿cómo calificaría la reputación de las empresas en las que ha laborado?": ["27. Overall, how would you rate the reputation of the companies where you have worked?", "27. Dans l'ensemble, comment évalueriez-vous la réputation des entreprises où vous avez travaillé ?"],
  "28. ¿Considera que sus capacidades, experiencia y conocimientos estuvieron de acuerdo con los puestos que ha desempeñado?": ["28. Do you think your skills, experience and knowledge matched the positions you have held?", "28. Estimez-vous que vos compétences, votre expérience et vos connaissances correspondaient aux postes que vous avez occupés ?"],
  "29. Durante el desempeño sus actividades profesionales, ¿obtuvo un mayor número de proyectos fracasados o exitosos?": ["29. In your professional activities, have you had more failed or successful projects?", "29. Dans vos activités professionnelles, avez-vous eu davantage de projets ratés ou réussis ?"],
  "30. Durante el desempeño de sus actividades profesionales, ¿ha participado en actos de corrupción o no éticos?": ["30. In your professional activities, have you taken part in corrupt or unethical acts?", "30. Dans vos activités professionnelles, avez-vous participé à des actes de corruption ou contraires à l'éthique ?"],
  "31. Los puestos que ha ocupado, así como el actual, ¿fueron conseguidos por mérito propio, o fue beneficiado por terceras personas?": ["31. Were the positions you have held, including your current one, earned on your own merit, or were you favored by third parties?", "31. Les postes que vous avez occupés, y compris l'actuel, ont-ils été obtenus par votre propre mérite ou avez-vous été favorisé par des tiers ?"],
  "32. ¿Se ha beneficiado de los puestos que ha ocupado para obtener algún beneficio personal, para cometer actos ilícitos o que se consideren no éticos?": ["32. Have you used the positions you have held for personal gain, or to commit unlawful or unethical acts?", "32. Avez-vous profité des postes que vous avez occupés pour en tirer un avantage personnel ou pour commettre des actes illicites ou contraires à l'éthique ?"],

  // Social
  "33. Entre las personas que conoce y que lo conocen, ¿hay individuos cuyo comportamiento sea ilegal o no ético?": ["33. Among the people you know and who know you, are there individuals whose behavior is illegal or unethical?", "33. Parmi les personnes que vous connaissez et qui vous connaissent, y a-t-il des individus dont le comportement est illégal ou contraire à l'éthique ?"],
  "34. Entre las personas que conoce y que lo conocen, ¿hay individuos que cometieron algún acto ilícito por el cual no hayan sido juzgados?": ["34. Among the people you know and who know you, are there individuals who committed an unlawful act for which they were not tried?", "34. Parmi les personnes que vous connaissez et qui vous connaissent, y a-t-il des individus ayant commis un acte illicite pour lequel ils n'ont pas été jugés ?"],
  "35. Entre las personas que son de su confianza, ¿hay individuos cuyo comportamiento sea ilegal o no ético?": ["35. Among the people you trust, are there individuals whose behavior is illegal or unethical?", "35. Parmi les personnes de confiance, y a-t-il des individus dont le comportement est illégal ou contraire à l'éthique ?"],
  "36. Entre las personas que son de su confianza, ¿hay individuos que cometieron algún acto ilícito por el cual no hayan sido juzgados?": ["36. Among the people you trust, are there individuals who committed an unlawful act for which they were not tried?", "36. Parmi les personnes de confiance, y a-t-il des individus ayant commis un acte illicite pour lequel ils n'ont pas été jugés ?"],
  "37. De manera general, ¿cómo calificaría la reputación de las personas que son de su confianza?": ["37. Overall, how would you rate the reputation of the people you trust?", "37. Dans l'ensemble, comment évalueriez-vous la réputation des personnes de confiance ?"],
  "38. Entre las personas que conoce y que lo conocen, ¿hay individuos cuyo rol laboral se le considere como persona políticamente expuesta?": ["38. Among the people you know and who know you, are there individuals whose job makes them a politically exposed person?", "38. Parmi les personnes que vous connaissez et qui vous connaissent, y a-t-il des individus dont la fonction en fait des personnes politiquement exposées ?"],
  "39. Entre las personas que conoce y que lo conocen ¿hay individuos que tengan implicaciones políticas?": ["39. Among the people you know and who know you, are there individuals with political involvement?", "39. Parmi les personnes que vous connaissez et qui vous connaissent, y a-t-il des individus ayant des implications politiques ?"],

  // Personal
  "40. Durante su vida adulta, ¿se ha conducido de forma ética, profesionalismo, respeto y sencillez?": ["40. During your adult life, have you behaved ethically, professionally, respectfully and modestly?", "40. Au cours de votre vie adulte, vous êtes-vous conduit avec éthique, professionnalisme, respect et simplicité ?"],
  "41. Durante su vida adulta, ¿se ha conducido de acuerdo con lo establecido por las leyes que rigen a su estado?": ["41. During your adult life, have you behaved in accordance with the laws that govern your state?", "41. Au cours de votre vie adulte, vous êtes-vous conduit conformément aux lois qui régissent votre État ?"],
  "42. ¿Ha cometido algún acto ilícito por el que no haya sido juzgado?": ["42. Have you committed an unlawful act for which you were not tried?", "42. Avez-vous commis un acte illicite pour lequel vous n'avez pas été jugé ?"],
  "43. ¿Tiene alguna preferencia marcada por algún partido político?": ["43. Do you have a strong preference for a political party?", "43. Avez-vous une préférence marquée pour un parti politique ?"],
  "44. ¿Tiene preferencias, hábitos personales y/o hábitos de consumo que puedan ser considerados como desagradables, de mal gusto o contrario a la moral o a las normas cívicas?": ["44. Do you have preferences, personal habits and/or consumption habits that could be considered unpleasant, in poor taste, or contrary to morals or civic norms?", "44. Avez-vous des préférences, des habitudes personnelles et/ou de consommation pouvant être jugées désagréables, de mauvais goût ou contraires à la morale ou aux règles civiques ?"],
  "45. ¿El contenido que crea, comenta, comparte y/o recomienda en redes sociales, sitios y/o blogs está apegado a las normas cívicas y morales?": ["45. Does the content you create, comment on, share and/or recommend on social media, websites and/or blogs follow civic and moral norms?", "45. Le contenu que vous créez, commentez, partagez et/ou recommandez sur les réseaux sociaux, sites et/ou blogs respecte-t-il les règles civiques et morales ?"],
  "46. ¿Tiene propiedades en el extranjero?": ["46. Do you own property abroad?", "46. Possédez-vous des biens à l'étranger ?"],
};
